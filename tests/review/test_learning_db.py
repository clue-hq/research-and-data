"""M13.3 — the learning loop on a live Postgres: enum parity, compute_yield, the config_revision
propose→promote lifecycle (reproducibility), the human-gate, and the backtest guardrail.

Skips without a DB (like the rest of the DB suites)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    ConfigRevisionStatus,
    ConfigRevisionTarget,
    EntityId,
    ExtractionMethod,
    ICPCreatedFrom,
    PromotionMode,
    ResearchMode,
    account_claim,
    new_run_id,
)
from clue_research.api import build_backtest_gate
from clue_research.claimstore import insert_claim
from clue_research.icp import (
    create_icp_spec,
    get_active_icp,
    get_icp_version,
    get_source_profile,
    rubric_to_slot,
)
from clue_research.icp.catalog import Pack, PackSourceSlot, register_pack_catalog
from clue_research.icp.rubric import RubricEntry, ScoringRubric, SubRubric
from clue_research.icp.source_profile import SourceWeight, WeightedSource
from clue_research.identity import insert_account_entity
from clue_research.review import (
    LearningLoopImpl,
    PromotionBlocked,
    compute_yield,
    get_config_revision,
    record_config_revision,
)
from clue_research.review.disposition import (
    DispositionType,
    FeedbackDisposition,
)
from clue_research.review.disposition_store import record_disposition
from clue_research.sources import record_source_yield

from .conftest import enum_labels, rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_review_db")

_CLIENT = "client-acme"
_ICP = "enterprise"
_PAIN = "account.operational_pain"
_FUNDING = "account.recent_funding"
_AT = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


def _rubric(field_key: str) -> ScoringRubric:
    """A minimal one-entry fit rubric over ``field_key`` (BOOLEAN: present → 1.0)."""
    return ScoringRubric(
        fit=SubRubric(entries=(RubricEntry(field_key=field_key, weight=1.0),)),
        intent=SubRubric(),
        label="base",
    )


async def _account(conn: AsyncConnection, name: str) -> EntityId:
    return await insert_account_entity(
        conn, canonical_name=name, primary_domain=f"{name}.com", status=AccountStatus.ACTIVE
    )


async def _field_claim(
    conn: AsyncConnection, account: EntityId, field_key: str, value: JsonValue
) -> None:
    await insert_claim(
        conn,
        account_claim(
            entity_id=account,
            field_key=field_key,
            value_json=value,
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.9,
            run_id=new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="https://news.example/x",
        ),
    )


async def _outcome(
    conn: AsyncConnection, account: EntityId, dtype: DispositionType, external_id: str
) -> None:
    await record_disposition(
        conn,
        FeedbackDisposition.for_downstream(
            disposition_type=dtype,
            account_entity_id=account,
            client_id=_CLIENT,
            external_id=external_id,
            occurred_at=_AT,
            icp_key=_ICP,
            icp_spec_version=1,
        ),
    )


def test_config_revision_enums_match_core() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            assert await enum_labels(conn, "config_revision_target") == [
                m.value for m in ConfigRevisionTarget
            ]
            assert await enum_labels(conn, "config_revision_status") == [
                m.value for m in ConfigRevisionStatus
            ]

    run_async(_run())


def test_compute_yield_telemetry_terms_reconcile() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                source_key="clay",
                icp_version=1,
                claims_total=10,
                claims_verified=8,
                cost_cents=Decimal("400"),
                freshness_seconds=int(90 * 86_400),
            )
            ym = await compute_yield(conn, client_id=_CLIENT, icp_key=_ICP, icp_spec_version=1)
            clay = next(s for s in ym.sources if s.source_key == "clay")
            assert clay.precision == 0.8  # 8 survived / 10 produced
            assert clay.cost_per_surviving_claim == Decimal("400") / 8
            assert clay.freshness_score == 0.5  # 90d over the 180d horizon
            assert clay.downstream_signal is None  # no sales outcomes seeded
            assert ym.has_downstream_signal is False

    run_async(_run())


def test_propose_and_promote_rubric_is_versioned_and_reproducible() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            base = _rubric(_PAIN)
            await create_icp_spec(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                created_from=ICPCreatedFrom.SYNTHESIS,
                scoring_rubric=rubric_to_slot(base),
                activate=True,
            )
            loop = LearningLoopImpl(conn_factory=_factory(conn))  # no backtest gate
            rev = await loop.propose_scoring_rubric_revision(client_id=_CLIENT, icp_key=_ICP)
            assert rev.target is ConfigRevisionTarget.SCORING_RUBRIC
            assert rev.status is ConfigRevisionStatus.PROPOSED
            assert rev.icp_spec_version == 1  # derived from the active v1

            applied = await loop.promote(rev.id, mode=PromotionMode.AUTO)
            assert applied == 2  # a NEW icp_spec version

            active = await get_active_icp(conn, _CLIENT, _ICP)
            assert active is not None and active.version == 2
            assert active.created_from is ICPCreatedFrom.FEEDBACK_REWEIGHT  # accurate provenance
            # Reproducibility: the prior version is unchanged and still readable.
            v1 = await get_icp_version(conn, _CLIENT, _ICP, 1)
            assert v1 is not None and v1.scoring_rubric == rubric_to_slot(base)
            # The ledger row is stamped promoted with the version it produced.
            promoted = await get_config_revision(conn, rev.id)
            assert promoted is not None
            assert promoted.status is ConfigRevisionStatus.PROMOTED
            assert promoted.applied_version == 2

    run_async(_run())


def test_out_of_bounds_rubric_promotion_requires_human() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await create_icp_spec(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                created_from=ICPCreatedFrom.SYNTHESIS,
                scoring_rubric=rubric_to_slot(_rubric(_PAIN)),
                activate=True,
            )
            rev = await record_config_revision(
                conn,
                target=ConfigRevisionTarget.SCORING_RUBRIC,
                client_id=_CLIENT,
                icp_key=_ICP,
                icp_spec_version=1,
                payload_json=rubric_to_slot(_rubric(_PAIN)),
                within_bounds=False,  # the cap bit → human gate
            )
            loop = LearningLoopImpl(conn_factory=_factory(conn))
            with pytest.raises(PromotionBlocked):
                await loop.promote(rev.id, mode=PromotionMode.AUTO)
            # The same revision promotes under an explicit human approval.
            applied = await loop.promote(rev.id, mode=PromotionMode.HUMAN, promoted_by="reviewer")
            assert applied == 2

    run_async(_run())


def test_propose_and_promote_source_profile_is_versioned_and_bounded() -> None:
    """AC: a source-profile reweight emits a NEW versioned override (the base pack profile is
    untouched), and a rejected-only source down-weights one ordinal level — never zeroed."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            pack = Pack(
                pack_key="learnpack",
                namespace="learn",
                title="Learn",
                source_profile=(
                    PackSourceSlot(
                        sources=(
                            WeightedSource(source_key="clay", weight=SourceWeight.HIGH, rank=1),
                        )
                    ),
                ),
            )
            await register_pack_catalog(conn, pack)
            # clay produced only rejected claims (precision 0) → it must down-weight one level.
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                source_key="clay",
                icp_version=1,
                claims_total=5,
                claims_verified=0,
            )
            loop = LearningLoopImpl(conn_factory=_factory(conn))
            rev = await loop.propose_source_profile_revision(
                client_id=_CLIENT, icp_key=_ICP, pack_key="learnpack", icp_spec_version=1
            )
            assert rev.target is ConfigRevisionTarget.SOURCE_PROFILE
            assert rev.within_bounds is True  # the ordinal one-level cap is always in-bounds
            assert any(m.key == "clay" for m in rev.explanation)  # the move is recorded
            # the decomposed explanation round-trips through the ledger (jsonb persist → parse).
            reread = await get_config_revision(conn, rev.id)
            assert reread is not None and any(m.key == "clay" for m in reread.explanation)

            applied = await loop.promote(rev.id, mode=PromotionMode.AUTO)  # no backtest on profiles
            assert (
                applied == 1
            )  # the first override version (append-only over the base pack profile)

            resolved = await get_source_profile(conn, "learnpack", client_id=_CLIENT, icp_key=_ICP)
            clay = next(s for s in resolved.default if s.source_key == "clay")
            assert clay.weight is SourceWeight.MEDIUM  # HIGH → MEDIUM (down one, not zeroed)

    run_async(_run())


def test_config_revision_proposal_is_idempotent() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            payload = {"pack_key": "p", "field_class": None, "weighted_sources": []}
            first = await record_config_revision(
                conn,
                target=ConfigRevisionTarget.SOURCE_PROFILE,
                client_id=_CLIENT,
                icp_key=_ICP,
                icp_spec_version=1,
                payload_json=payload,
            )
            again = await record_config_revision(
                conn,
                target=ConfigRevisionTarget.SOURCE_PROFILE,
                client_id=_CLIENT,
                icp_key=_ICP,
                icp_spec_version=1,
                payload_json=payload,
            )
            assert again.id == first.id  # ON CONFLICT DO NOTHING → the same lineage row

    run_async(_run())


# --- the backtest guardrail (the M13.3 headline AC) -----------------------------------------------


async def _seed_backtest_world(conn: AsyncConnection) -> None:
    """An accepted account that the baseline (pain) rubric ranks high, and a rejected one it ranks
    low — so the baseline discriminates and a rubric that inverts the signal regresses."""
    await create_icp_spec(
        conn,
        client_id=_CLIENT,
        icp_key=_ICP,
        created_from=ICPCreatedFrom.SYNTHESIS,
        scoring_rubric=rubric_to_slot(_rubric(_PAIN)),
        activate=True,
    )
    accepted = await _account(conn, "winner")
    rejected = await _account(conn, "loser")
    await _field_claim(conn, accepted, _PAIN, "real pain")  # baseline rewards this
    # only the inverted rubric rewards this (recent_funding's schema is an object).
    await _field_claim(conn, rejected, _FUNDING, {"amount_usd": 5_000_000, "round": "series_b"})
    await _outcome(conn, accepted, DispositionType.ACCOUNT_ACCEPTED, "ext-win")
    await _outcome(conn, rejected, DispositionType.ACCOUNT_REJECTED, "ext-lose")


def test_backtest_blocks_a_regressing_rubric() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _seed_backtest_world(conn)
            gate = build_backtest_gate(conn_factory=_factory(conn))
            # A rubric that rewards FUNDING inverts the ranking (the rejected account scores high).
            verdict = await gate.backtest(
                rubric_to_slot(_rubric(_FUNDING)),
                client_id=_CLIENT,
                icp_key=_ICP,
                baseline_version=1,
            )
            assert verdict.passed is False  # AUC regressed → promotion blocked
            assert verdict.regressions  # the regressed metric is recorded
            assert verdict.sample_size == 2

    run_async(_run())


def test_backtest_passes_a_non_regressing_rubric() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _seed_backtest_world(conn)
            gate = build_backtest_gate(conn_factory=_factory(conn))
            # The same rubric as the baseline ⇒ identical AUC ⇒ no regression.
            verdict = await gate.backtest(
                rubric_to_slot(_rubric(_PAIN)),
                client_id=_CLIENT,
                icp_key=_ICP,
                baseline_version=1,
            )
            assert verdict.passed is True

    run_async(_run())
