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
from clue_research.discovery_scoring.gate.admission import (
    DISCOVERY_PROVENANCE_FIELD,
    IMPORT_CHANNEL,
)
from clue_research.identity import (
    DispositionPolicy,
    embed_account,
    get_account,
    insert_account_entity,
    list_open_tasks,
)
from clue_research.membership import accounts_for_project, projects_for_accounts
from clue_storage import artifact_key, content_address, record_artifact
from tests._workspace import DEFAULT_TEST_WORKSPACE as WS
from tests._workspace import seed_project, seed_workspace

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


async def _added_via(conn: AsyncConnection, entity_id: EntityId) -> list[str]:
    """The recorded membership channels for an account (the one fact the readers do not expose)."""
    rows = await conn.execute(
        text(
            "SELECT added_via FROM project_account WHERE account_entity_id = :id ORDER BY added_at"
        ),
        {"id": entity_id},
    )
    return [str(value) for value in rows.scalars()]


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


def test_durable_item_artifact_is_the_provenance_replay_identity() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_run_id()
            item_one_sha = content_address(b"item-1")
            item_two_sha = content_address(b"item-2")
            item_one_key = artifact_key(WS, item_one_sha)
            item_two_key = artifact_key(WS, item_two_sha)
            for key, digest in ((item_one_key, item_one_sha), (item_two_key, item_two_sha)):
                await record_artifact(
                    conn,
                    storage_key=key,
                    workspace_id=WS,
                    content_sha256=digest,
                    media_type="application/json",
                    size_bytes=6,
                    source_key="exa_websets",
                )
            first = await admit(
                conn,
                candidate(
                    matched_channel="exa_websets",
                    record_ref="item-1",
                    domain="same.example",
                    name="Same Company",
                    artifact_key=item_one_key,
                    evidence_span="criterion=yes",
                    discovery_evidence={"provider_item_id": "item-1"},
                ),
                run_id,
                workspace_id=WS,
            )
            replay = await admit(
                conn,
                candidate(
                    matched_channel="exa_websets",
                    record_ref="item-1",
                    domain="same.example",
                    name="Same Company",
                    artifact_key=item_one_key,
                    evidence_span="criterion=yes",
                    discovery_evidence={"provider_item_id": "item-1"},
                ),
                run_id,
                workspace_id=WS,
            )
            second_item = await admit(
                conn,
                candidate(
                    matched_channel="exa_websets",
                    record_ref="item-2",
                    domain="same.example",
                    name="Same Company",
                    artifact_key=item_two_key,
                    evidence_span="criterion=unclear",
                    discovery_evidence={"provider_item_id": "item-2"},
                ),
                run_id,
                workspace_id=WS,
            )

            assert (
                first.account_entity_id == replay.account_entity_id == second_item.account_entity_id
            )
            assert first.discovery_provenance_claim_id == replay.discovery_provenance_claim_id
            assert second_item.discovery_provenance_claim_id != first.discovery_provenance_claim_id
            assert first.account_entity_id is not None
            claims = await _provenance_claims(conn, first.account_entity_id)
            assert {claim.artifact_key for claim in claims} == {
                item_one_key,
                item_two_key,
            }

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


def test_admit_records_project_membership_for_a_new_account() -> None:
    """FI-2 P1 (spec §2): an admitted candidate joins the admitting project's target list.

    Read back through the real membership readers, not the row — the frontend's ``projects[]``
    and a project's target-account list are what this write exists to serve.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, WS, name="Discovery project")
            result = await admit(
                conn,
                candidate(matched_channel="exa", domain="joined.example", name="Joined Co"),
                new_run_id(),
                workspace_id=WS,
                project_id=project.project_id,
            )
            assert result.status is AdmissionStatus.ADMITTED
            assert result.account_entity_id is not None
            assert await accounts_for_project(
                conn, workspace_id=WS, project_id=project.project_id
            ) == (result.account_entity_id,)
            assert await projects_for_accounts(
                conn, workspace_id=WS, account_ids=[result.account_entity_id]
            ) == {result.account_entity_id: (project.project_id,)}
            assert await _added_via(conn, result.account_entity_id) == ["discovered"]

    run_async(_run())


def test_admit_records_membership_on_the_survivor_of_an_auto_merge() -> None:
    """An admission that auto-merges onto an *existing* account still joins *this* project.

    The account is workspace-global (R1) and may already belong to another project; membership is
    per (project, account), so the second project's add lands on the survivor.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            first = await seed_project(conn, WS, name="First project")
            second = await seed_project(conn, WS, name="Second project")
            acme = await _seed(conn, canonical_name="Acme", primary_domain="acme-merge.example")
            await admit(
                conn,
                candidate(domain="acme-merge.example", name="Acme"),
                new_run_id(),
                workspace_id=WS,
                project_id=first.project_id,
            )
            result = await admit(
                conn,
                candidate(record_ref="rec:2", domain="acme-merge.example", name="Acme Inc"),
                new_run_id(),
                workspace_id=WS,
                project_id=second.project_id,
            )
            assert result.status is AdmissionStatus.ADMITTED
            assert result.account_entity_id == acme  # auto-merged onto the existing entity
            assert await projects_for_accounts(conn, workspace_id=WS, account_ids=[acme]) == {
                acme: (first.project_id, second.project_id)
            }

    run_async(_run())


def test_admit_writes_no_membership_for_a_review_band_candidate() -> None:
    """A mid-band (``ENQUEUED``) admission admits no entity, so it joins no project either.

    Membership follows the *resolved* account; until the M2 review resolves the task there is no
    account to attach (and the review-resolution path carries no project context — FI-2 gap).
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, WS, name="Review project")
            await _seed(conn, canonical_name="Acme Corporation")  # name-only, embedded
            policy = DispositionPolicy(
                version=9, review_low_threshold=0.3, auto_merge_threshold=0.99
            )
            result = await admit(
                conn,
                candidate(matched_channel="exa", name="Acme Corporation"),
                new_run_id(),
                workspace_id=WS,
                project_id=project.project_id,
                disposition_policy=policy,
            )
            assert result.status is AdmissionStatus.NEEDS_REVIEW
            assert (
                await accounts_for_project(conn, workspace_id=WS, project_id=project.project_id)
                == ()
            )

    run_async(_run())


def test_admit_records_an_import_channel_candidate_as_imported() -> None:
    """The gate is channel-agnostic but membership is not: the reserved ``import`` channel records
    ``added_via='imported'`` — one gate, two entry scenarios (Doc B §4), two truthful channels."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, WS, name="Import project")
            result = await admit(
                conn,
                candidate(
                    matched_channel=IMPORT_CHANNEL, domain="imported.example", name="Imported Co"
                ),
                new_run_id(),
                workspace_id=WS,
                project_id=project.project_id,
            )
            assert result.status is AdmissionStatus.ADMITTED
            assert result.account_entity_id is not None
            assert await _added_via(conn, result.account_entity_id) == ["imported"]

    run_async(_run())


def test_admit_without_project_context_writes_no_membership() -> None:
    """A projectless admission still admits the account — membership is the project's claim on it,
    and a workspace-level admission simply makes none (the account is global, R1)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            result = await admit(
                conn,
                candidate(matched_channel="exa", domain="projectless.example", name="No Project"),
                new_run_id(),
                workspace_id=WS,
            )
            assert result.status is AdmissionStatus.ADMITTED
            assert result.account_entity_id is not None
            assert (
                await projects_for_accounts(
                    conn, workspace_id=WS, account_ids=[result.account_entity_id]
                )
                == {}
            )

    run_async(_run())


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
