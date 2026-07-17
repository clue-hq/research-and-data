"""M2.3 (ENG-112) — auto-merge + the human review queue, against a live Postgres.

Covers every §M2.3 acceptance criterion: the auto-merge executor (union + idempotent + append-only
claims), the three disposition bands, the review resolve API (merge_into / not_a_match /
create_new_entity / split), claims readable under the survivor with no claim UPDATE, config-driven
band movement, and the disposition audit.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_core import (
    AccountStatus,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    account_claim,
    new_run_id,
)
from clue_research.claimstore import ALL_TENANTS, TenantScope, insert_claim
from clue_research.identity import (
    DispositionOutcome,
    DispositionPolicy,
    MergeConflictError,
    Observation,
    ReviewStatus,
    auto_merge,
    current_value_resolved,
    disposition,
    embed_account,
    enqueue_review_task,
    get_account,
    get_dispositions,
    get_task,
    insert_account_entity,
    list_open_tasks,
    mark_merged,
    resolve,
    resolve_create_new_entity,
    resolve_merge_into,
    resolve_not_a_match,
    split_merge,
    surviving_id,
)
from clue_research.identity.review import (
    DispositionKind,
    ReviewResolution,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_identity_db")


async def _seed(conn: object, **kwargs: object) -> object:
    eid = await insert_account_entity(conn, **kwargs)  # type: ignore[arg-type]
    await embed_account(conn, eid)  # type: ignore[arg-type]
    return eid


def test_db_enums_match_python() -> None:
    """The migration's review/disposition enum labels stay in lock-step with the Python enums."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            for typ, enum in (
                ("review_status", ReviewStatus),
                ("review_resolution", ReviewResolution),
                ("disposition_kind", DispositionKind),
            ):
                labels = {
                    r[0]
                    for r in (
                        await conn.execute(
                            text(
                                "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e "
                                "ON e.enumtypid = t.oid WHERE t.typname = :t"
                            ),
                            {"t": typ},
                        )
                    ).all()
                }
                assert labels == {m.value for m in enum}

    run_async(_run())


def test_auto_merge_executor_unions_and_is_idempotent() -> None:
    """A merge sets status/merged_into, unions aliases+registry onto the survivor, and is a no-op
    on a second call (idempotent on the pair)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            survivor = await insert_account_entity(
                conn, canonical_name="Acme", registry_ids={"DUNS": "111"}
            )
            loser = await insert_account_entity(
                conn,
                canonical_name="Acme Corporation",
                primary_domain="acme.com",
                aliases=["acme labs"],
                registry_ids={"LEI": "222"},
            )
            result = await auto_merge(conn, loser, survivor, top_score=1.0, config_version=1)
            assert result == survivor

            loser_rec = await get_account(conn, loser)
            assert loser_rec is not None and loser_rec.status is AccountStatus.MERGED
            assert loser_rec.merged_into == survivor
            assert await surviving_id(conn, loser, EntityType.ACCOUNT) == survivor

            surv = await get_account(conn, survivor)
            assert surv is not None
            assert surv.registry_ids == {"DUNS": "111", "LEI": "222"}  # union
            assert "acme labs" in surv.aliases  # loser alias absorbed
            assert surv.primary_domain == "acme.com"  # gap filled from loser

            # Idempotent: a repeat merge is a true no-op — it records NO second disposition.
            assert await auto_merge(conn, loser, survivor) == survivor
            merges = [
                r
                for r in await get_dispositions(conn, survivor)
                if r["kind"] == DispositionKind.AUTO_MERGE.value
            ]
            assert len(merges) == 1

    run_async(_run())


def test_auto_merge_refuses_to_repoint_an_already_merged_loser() -> None:
    """Re-pointing a loser already merged into a different survivor raises (no corruption)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            survivor1 = await insert_account_entity(conn, canonical_name="Acme One")
            survivor2 = await insert_account_entity(conn, canonical_name="Acme Two")
            loser = await insert_account_entity(conn, canonical_name="Acme Loser")
            await auto_merge(conn, loser, survivor1)
            with pytest.raises(MergeConflictError):
                await auto_merge(conn, loser, survivor2)
            # The original merge is intact.
            assert await surviving_id(conn, loser, EntityType.ACCOUNT) == survivor1

    run_async(_run())


def test_split_restores_relinquished_strong_keys() -> None:
    """split is a true inverse: the loser gets its domain back and the survivor releases it."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            survivor = await insert_account_entity(conn, canonical_name="Acme")  # no domain
            loser = await insert_account_entity(
                conn, canonical_name="Acme Two", primary_domain="acme.com"
            )
            await auto_merge(conn, loser, survivor)
            # After merge: survivor absorbed the domain; loser relinquished it.
            assert (await get_account(conn, survivor)).primary_domain == "acme.com"  # type: ignore[union-attr]
            assert (await get_account(conn, loser)).primary_domain is None  # type: ignore[union-attr]

            await split_merge(conn, loser, resolved_by="reviewer-x")
            # After split: loser whole again with its domain; survivor released it (no clash).
            loser_rec = await get_account(conn, loser)
            assert loser_rec is not None
            assert loser_rec.primary_domain == "acme.com"
            assert loser_rec.merged_into is None
            assert (await get_account(conn, survivor)).primary_domain is None  # type: ignore[union-attr]

    run_async(_run())


def test_disposition_auto_merges_on_deterministic_hit() -> None:
    """A deterministic (strong-key) resolution auto-merges: the observation resolves to the existing
    entity, and the disposition is audited."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            acme = await _seed(conn, canonical_name="Acme", primary_domain="acme.com")
            result = await resolve(conn, Observation(name="Acme Inc", domain="acme.com"))
            disp = await disposition(conn, Observation(name="Acme Inc", domain="acme.com"), result)
            assert disp.outcome is DispositionOutcome.AUTO_MERGED
            assert disp.entity_id == acme
            audit = await get_dispositions(conn, acme)
            assert any(r["kind"] == DispositionKind.AUTO_MERGE.value for r in audit)

    run_async(_run())


def test_disposition_mid_band_enqueues_review_and_mutates_nothing() -> None:
    """A mid-band match creates exactly one open task and mutates no entity (never silently
    collapse)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            us = await _seed(
                conn,
                canonical_name="Apex Logistics",
                primary_domain="apex.com",
                hq_geo={"country": "US"},
            )
            de = await _seed(
                conn,
                canonical_name="Apex Logistics",
                primary_domain="apex.de",
                hq_geo={"country": "DE"},
            )
            obs = Observation(name="Apex Logistics", geo={"country": "US"})
            result = await resolve(conn, obs)
            assert 0.70 <= result.top_score < 0.95  # mid-band by construction
            disp = await disposition(conn, obs, result)
            assert disp.outcome is DispositionOutcome.ENQUEUED
            tasks = await list_open_tasks(conn)
            assert len(tasks) == 1 and tasks[0].id == disp.task_id
            # Neither entity changed.
            assert (await get_account(conn, us)).status is AccountStatus.CANDIDATE  # type: ignore[union-attr]
            assert (await get_account(conn, de)).status is AccountStatus.CANDIDATE  # type: ignore[union-attr]

    run_async(_run())


def test_disposition_below_low_admits_new_candidate() -> None:
    """A below-low-threshold observation admits a fresh candidate entity and creates no task."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            obs = Observation(name="Totally New Co", domain="totallynew.example")
            result = await resolve(conn, obs)  # empty store → no candidates
            disp = await disposition(conn, obs, result)
            assert disp.outcome is DispositionOutcome.NEW_ENTITY
            assert disp.entity_id is not None
            new = await get_account(conn, disp.entity_id)
            assert new is not None and new.status is AccountStatus.CANDIDATE
            assert await list_open_tasks(conn) == []

    run_async(_run())


def test_review_resolve_merge_into_applies_merge() -> None:
    """Resolving a task via merge_into merges the subject into the survivor and closes the task."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            survivor = await _seed(conn, canonical_name="Acme", primary_domain="acme.com")
            subject = await insert_account_entity(conn, canonical_name="Acme Co")
            obs = Observation(name="Acme Co")
            result = await resolve(conn, obs)
            task_id = await enqueue_review_task(
                conn, obs, result, config_version=1, subject_entity_id=subject
            )
            returned = await resolve_merge_into(conn, task_id, survivor, resolved_by="reviewer-1")
            assert returned == survivor
            assert await surviving_id(conn, subject, EntityType.ACCOUNT) == survivor
            task = await get_task(conn, task_id)
            assert task is not None and task.status is ReviewStatus.RESOLVED
            assert task.resolution is ReviewResolution.MERGE_INTO
            assert task.resolved_by == "reviewer-1"

    run_async(_run())


def test_review_resolve_not_a_match_keeps_both() -> None:
    """not_a_match keeps the subject distinct and closes the task without any merge."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            existing = await _seed(conn, canonical_name="Apex Logistics", hq_geo={"country": "US"})
            subject = await insert_account_entity(
                conn, canonical_name="Apex Logistics", hq_geo={"country": "DE"}
            )
            obs = Observation(name="Apex Logistics", geo={"country": "DE"})
            result = await resolve(conn, obs)
            task_id = await enqueue_review_task(
                conn, obs, result, config_version=1, subject_entity_id=subject
            )
            await resolve_not_a_match(conn, task_id, resolved_by="reviewer-2")
            # Both remain distinct, unmerged.
            assert await surviving_id(conn, subject, EntityType.ACCOUNT) == subject
            assert await surviving_id(conn, existing, EntityType.ACCOUNT) == existing
            task = await get_task(conn, task_id)
            assert task is not None and task.resolution is ReviewResolution.NOT_A_MATCH

    run_async(_run())


def test_review_resolve_create_new_entity() -> None:
    """create_new_entity admits a fresh entity from the observation and closes the task."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            obs = Observation(name="Brand New Corp", domain="brandnew.example")
            result = await resolve(conn, obs)
            task_id = await enqueue_review_task(conn, obs, result, config_version=1)
            new_id = await resolve_create_new_entity(conn, task_id, resolved_by="reviewer-3")
            new = await get_account(conn, new_id)
            assert new is not None and new.canonical_name == "Brand New Corp"
            task = await get_task(conn, task_id)
            assert task is not None and task.resolution is ReviewResolution.CREATE_NEW_ENTITY

    run_async(_run())


def test_split_reverses_a_merge() -> None:
    """split un-points merged_into and re-activates the loser (reversing an erroneous merge)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            survivor = await insert_account_entity(conn, canonical_name="Acme")
            loser = await insert_account_entity(conn, canonical_name="Acme Two")
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)
            assert await surviving_id(conn, loser, EntityType.ACCOUNT) == survivor
            await split_merge(conn, loser, resolved_by="reviewer-4")
            assert await surviving_id(conn, loser, EntityType.ACCOUNT) == loser
            rec = await get_account(conn, loser)
            assert (
                rec is not None and rec.status is AccountStatus.ACTIVE and rec.merged_into is None
            )

    run_async(_run())


def test_claims_readable_under_survivor_with_no_claim_update() -> None:
    """After a merge, a claim attached to the loser is read under the survivor via
    current_value_resolved, and the claim row is never UPDATEd (append-only preserved)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            survivor = await insert_account_entity(conn, canonical_name="Acme")
            loser = await insert_account_entity(conn, canonical_name="Acme Two")
            claim = account_claim(
                entity_id=loser,
                field_key="account.recent_funding",
                value_json={"round": "B"},
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                source_url="https://api.example.com/acme",
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
            )
            claim_id = await insert_claim(conn, claim, validate_field=False)
            await auto_merge(conn, loser, survivor)

            cv = await current_value_resolved(
                conn, survivor, "account.recent_funding", scope=ALL_TENANTS
            )
            assert cv is not None and cv.value_json == {"round": "B"}

            # The claim row is untouched: still entity_id=loser, never superseded.
            row = (
                await conn.execute(
                    text("SELECT entity_id, superseded_by FROM claim WHERE id = :id"),
                    {"id": claim_id},
                )
            ).first()
            assert row is not None
            assert row[0] == loser and row[1] is None

    run_async(_run())


def test_merge_resolved_read_does_not_leak_across_tenants() -> None:
    """REGRESSION: current_value_resolved is tenant-scoped — a loser's tenant_private claim is read
    under the survivor for its OWN tenant, but never surfaces to another tenant (M2.5)."""

    async def _run() -> None:
        from clue_core import ReuseScope

        async with rollback_conn() as conn:
            survivor = await insert_account_entity(conn, canonical_name="Acme")
            loser = await insert_account_entity(conn, canonical_name="Acme Two")
            private = account_claim(
                entity_id=loser,
                field_key="account.scoring_fit",
                value_json={"score": 0.9},
                source_tier=1,
                extraction_method=ExtractionMethod.CRM_IMPORT,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
            ).model_copy(update={"reuse_scope": ReuseScope.TENANT_PRIVATE, "tenant_id": "tenant-a"})
            await insert_claim(conn, private, validate_field=False)
            await auto_merge(conn, loser, survivor)

            field = "account.scoring_fit"
            # Tenant B: the loser's private claim must NOT be visible under the merge.
            b = await current_value_resolved(
                conn, survivor, field, scope=TenantScope.for_tenant("tenant-b")
            )
            assert b is None
            # Tenant A: its own private claim IS visible under the survivor.
            a = await current_value_resolved(
                conn, survivor, field, scope=TenantScope.for_tenant("tenant-a")
            )
            assert a is not None and a.value_json == {"score": 0.9}
            # Public-only view: nothing (it is private).
            assert (
                await current_value_resolved(conn, survivor, field, scope=TenantScope.public_only())
                is None
            )

    run_async(_run())


def test_threshold_config_moves_borderline_pair() -> None:
    """Changing the threshold config version moves a borderline pair between review and auto-merge,
    with no code change (policy is data)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await _seed(conn, canonical_name="Apex Logistics", hq_geo={"country": "US"})
            obs = Observation(name="Apex Logistics", geo={"country": "US"})
            result = await resolve(conn, obs)
            assert 0.70 <= result.top_score < 0.95

            # Default policy (auto=0.95): the borderline pair routes to review.
            default = await disposition(conn, obs, result)
            assert default.outcome is DispositionOutcome.ENQUEUED

            # A more aggressive policy version (auto=0.70): the same pair now auto-merges.
            aggressive = DispositionPolicy(version=2, auto_merge_threshold=0.70)
            moved = await disposition(conn, obs, result, policy=aggressive)
            assert moved.outcome is DispositionOutcome.AUTO_MERGED

    run_async(_run())


def test_auto_merge_acquires_redis_locks_and_completes() -> None:
    """The merge path locks both candidates (M2.4 multi_lock) and completes (needs Redis)."""

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
                survivor = await insert_account_entity(conn, canonical_name="Acme")
                loser = await insert_account_entity(conn, canonical_name="Acme Two")
                result = await auto_merge(conn, loser, survivor, redis=client)
                assert result == survivor
                assert await surviving_id(conn, loser, EntityType.ACCOUNT) == survivor
        finally:
            await client.aclose()

    run_async(_run())


def test_every_disposition_is_audited() -> None:
    """Every disposition is retrievable as an audit record with score + decider + config version."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            survivor = await insert_account_entity(conn, canonical_name="Acme")
            loser = await insert_account_entity(conn, canonical_name="Acme Two")
            await auto_merge(
                conn, loser, survivor, top_score=1.0, decided_by="auto", config_version=7
            )
            audit = await get_dispositions(conn, survivor)
            assert audit
            top = audit[0]
            assert top["decided_by"] == "auto"
            assert top["config_version"] == 7
            assert top["top_score"] is not None

    run_async(_run())
