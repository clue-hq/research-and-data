"""M1.1 (ENG-102) — the append-only `claim` table, its triggers, CHECKs, and write helpers.

Every §M1.1 acceptance criterion has a dedicated test here, exercised against a live Postgres
(skips without one). Negative cases use raw SQL deliberately — to drive the DB constraint/trigger
directly — but every *write in a caller path* goes through ``insert_claim`` / ``supersede_claim``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_research.claimstore import claims_for, insert_claim, supersede_claim
from clue_research.core import (
    Claim,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    VerificationStatus,
    new_entity_id,
    new_run_id,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

# A raw INSERT used only by negative tests, to drive the DB CHECKs directly (bypassing the model,
# which would reject the bad value at construction). Every NOT NULL column is supplied.
_RAW_INSERT = text(
    """
    INSERT INTO claim (entity_id, entity_type, field_key, value_json, source_tier,
                       extraction_method, evidence_span, confidence, run_id, research_mode,
                       verification_status)
    VALUES (:entity_id, 'account', 'account.recent_funding', CAST(:value_json AS jsonb),
            :source_tier, CAST(:extraction_method AS extraction_method), :evidence_span,
            :confidence, :run_id, 'account_profiling',
            CAST(:verification_status AS verification_status))
    RETURNING id
    """
)


def _raw_params(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "entity_id": new_entity_id(),
        "value_json": "{}",
        "source_tier": 1,
        "extraction_method": "api",
        "evidence_span": None,
        "confidence": 0.9,
        "run_id": new_run_id(),
        "verification_status": "unverified",
    }
    params.update(overrides)
    return params


def test_db_enums_match_core() -> None:
    """The migration's enum value sets stay in lock-step with the core StrEnums (drift guard)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT t.typname, e.enumlabel "
                        "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                        "WHERE t.typname IN "
                        "('entity_type','extraction_method','research_mode','verification_status')"
                    )
                )
            ).all()
        by_type: dict[str, set[str]] = {}
        for typname, label in rows:
            by_type.setdefault(typname, set()).add(label)
        assert by_type["entity_type"] == {m.value for m in EntityType}
        assert by_type["extraction_method"] == {m.value for m in ExtractionMethod}
        assert by_type["research_mode"] == {m.value for m in ResearchMode}
        assert by_type["verification_status"] == {m.value for m in VerificationStatus}

    run_async(_run())


def test_claim_schema_present_at_head() -> None:
    """Migrating up created `claim` with every §4 column plus verification_status."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            cols = set(
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'claim'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        expected = {
            "id",
            "entity_id",
            "entity_type",
            "field_key",
            "value_json",
            "source_url",
            "source_tier",
            "extraction_method",
            "evidence_span",
            "confidence",
            "corroborations",
            "observed_at",
            "collected_at",
            "cost_cents",
            "run_id",
            "research_mode",
            "superseded_by",
            "verification_status",
        }
        assert expected <= cols, f"missing claim columns: {expected - cols}"

    run_async(_run())


def test_insert_persists_provenance_and_autostamps(make_account: Callable[..., Claim]) -> None:
    """insert_claim() persists all provenance fields; collected_at + unverified are stamped."""

    async def _run() -> None:
        claim = make_account(
            value_json={"amount_usd": 5_000_000},
            confidence=0.77,
            evidence_span="raised $5M Series A",
            source_url="https://news.example/funding",
        )
        async with rollback_conn() as conn:
            claim_id = await insert_claim(conn, claim)
            (stored,) = await claims_for(conn, claim.entity_id)
        assert stored.id == claim_id
        assert stored.value_json == {"amount_usd": 5_000_000}
        assert stored.confidence == pytest.approx(0.77)
        assert stored.evidence_span == "raised $5M Series A"
        assert stored.source_url == "https://news.example/funding"
        assert stored.collected_at is not None
        assert stored.verification_status is VerificationStatus.UNVERIFIED

    run_async(_run())


def test_immutable_update_is_rejected(make_account: Callable[..., Claim]) -> None:
    """Updating an immutable provenance column is rejected by the append-only trigger."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            claim_id = await insert_claim(conn, make_account())
            for column, value in (
                ("value_json", "'[1,2,3]'::jsonb"),
                ("source_url", "'https://evil.example'"),
                ("source_tier", "2"),
                ("evidence_span", "'rewritten'"),
            ):
                trans = await conn.begin_nested()
                with pytest.raises(DBAPIError, match="append-only"):
                    await conn.execute(
                        text(f"UPDATE claim SET {column} = {value} WHERE id = :id"),
                        {"id": claim_id},
                    )
                await trans.rollback()

    run_async(_run())


def test_allowed_columns_can_be_updated(make_account: Callable[..., Claim]) -> None:
    """The allow-list columns (verification_status, corroborations, superseded_by) may change."""

    async def _run() -> None:
        claim = make_account()
        async with rollback_conn() as conn:
            claim_id = await insert_claim(conn, claim)
            await conn.execute(
                text(
                    "UPDATE claim SET verification_status = 'verified', corroborations = 3 "
                    "WHERE id = :id"
                ),
                {"id": claim_id},
            )
            (row,) = await claims_for(conn, claim.entity_id)
        assert row.id == claim_id
        assert row.verification_status is VerificationStatus.VERIFIED
        assert row.corroborations == 3

    run_async(_run())


def test_delete_is_rejected(make_account: Callable[..., Claim]) -> None:
    """Rows cannot be deleted (append-only; erasure/tombstoning is M10.5)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            claim_id = await insert_claim(conn, make_account())
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(text("DELETE FROM claim WHERE id = :id"), {"id": claim_id})

    run_async(_run())


def test_supersede_links_old_and_keeps_history(make_account: Callable[..., Claim]) -> None:
    """supersede_claim() inserts a new row, sets old.superseded_by, preserves full history."""

    async def _run() -> None:
        old = make_account(value_json={"amount_usd": 1_000_000})
        new = make_account(value_json={"amount_usd": 9_000_000})
        assert old.entity_id == new.entity_id  # same fixture entity within this test
        async with rollback_conn() as conn:
            old_id = await insert_claim(conn, old)
            new_id = await supersede_claim(conn, old_id, new)

            live = await claims_for(conn, old.entity_id)
            full = await claims_for(conn, old.entity_id, include_superseded=True)
            old_superseded_by = (
                await conn.execute(
                    text("SELECT superseded_by FROM claim WHERE id = :id"), {"id": old_id}
                )
            ).scalar_one()

        # Default reader returns only the live (new) claim; history holds both.
        assert [c.id for c in live] == [new_id]
        assert {c.id for c in full} == {old_id, new_id}
        # The old row's provenance is untouched; it only gained the forward pointer.
        assert old_superseded_by == new_id

    run_async(_run())


def test_tier4_without_span_cannot_be_verified() -> None:
    """A tier-4 claim with no evidence_span can exist (unverified) but cannot become verified."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            # tier-4 must be llm_synthesis (the tier4-iff-synthesis CHECK); insert it unverified.
            spanless_id = (
                await conn.execute(
                    _RAW_INSERT,
                    _raw_params(source_tier=4, extraction_method="llm_synthesis"),
                )
            ).scalar_one()
            # Promoting the span-less tier-4 claim to verified violates the evidence-span CHECK.
            trans = await conn.begin_nested()
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text("UPDATE claim SET verification_status = 'verified' WHERE id = :id"),
                    {"id": spanless_id},
                )
            await trans.rollback()

            # The same tier-4 claim *with* a span can be verified.
            spanned_id = (
                await conn.execute(
                    _RAW_INSERT,
                    _raw_params(
                        source_tier=4,
                        extraction_method="llm_synthesis",
                        evidence_span="model cited this sentence",
                    ),
                )
            ).scalar_one()
            await conn.execute(
                text("UPDATE claim SET verification_status = 'verified' WHERE id = :id"),
                {"id": spanned_id},
            )
            status = (
                await conn.execute(
                    text("SELECT verification_status FROM claim WHERE id = :id"),
                    {"id": spanned_id},
                )
            ).scalar_one()
        assert status == "verified"

    run_async(_run())


def test_check_constraints_reject_out_of_range() -> None:
    """CHECKs reject source_tier 0/5 and confidence -0.1/1.1."""

    async def _run() -> None:
        bad = [
            _raw_params(source_tier=0),
            _raw_params(source_tier=5),
            _raw_params(confidence=-0.1),
            _raw_params(confidence=1.1),
        ]
        async with rollback_conn() as conn:
            for params in bad:
                trans = await conn.begin_nested()
                with pytest.raises(DBAPIError):
                    await conn.execute(_RAW_INSERT, params)
                await trans.rollback()

    run_async(_run())


def test_live_claims_partial_index_is_used(make_account: Callable[..., Claim]) -> None:
    """The (entity_id, field_key) WHERE superseded_by IS NULL partial index serves the hot read."""

    async def _run() -> None:
        claim = make_account()
        async with rollback_conn() as conn:
            await insert_claim(conn, claim)
            # Disable seqscan so the planner must use an index if the predicate is indexable; the
            # live-claims query then proves the partial index covers it.
            await conn.execute(text("SET LOCAL enable_seqscan = off"))
            plan_rows = (
                (
                    await conn.execute(
                        text(
                            "EXPLAIN SELECT id FROM claim "
                            "WHERE entity_id = :e AND field_key = :f AND superseded_by IS NULL"
                        ),
                        {"e": claim.entity_id, "f": claim.field_key},
                    )
                )
                .scalars()
                .all()
            )
        plan = "\n".join(plan_rows)
        assert "claim_live_entity_field" in plan, plan

    run_async(_run())


def test_observed_at_roundtrips_utc(make_account: Callable[..., Claim]) -> None:
    """observed_at is stored/returned as a tz-aware UTC timestamp."""

    async def _run() -> None:
        observed = datetime.now(UTC) - timedelta(days=10)
        claim = make_account(observed_at=observed)
        async with rollback_conn() as conn:
            await insert_claim(conn, claim)
            (stored,) = await claims_for(conn, claim.entity_id)
        assert stored.observed_at is not None
        assert stored.observed_at.tzinfo is not None
        assert stored.observed_at == observed

    run_async(_run())
