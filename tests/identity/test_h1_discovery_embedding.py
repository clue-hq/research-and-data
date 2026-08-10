"""FI-2 slice-0 H1 — a discovery-created account is embedded (and admission carries its aliases).

The defect this pins (spec ``docs/specs/FI-2-workspace-account-layer.md`` §1.2-H1):
``embed_account`` had exactly three call sites (import, seeds, client-KB), so the
admission/disposition *new-entity* path minted an account with **no**
``account_entity_embedding`` row. A later name-only encounter of the same company then scored
with the cosine arm zeroed — below the 0.70 review floor — and silently
minted a **duplicate** instead of routing to human review. The M2.3 mid-band test
(``test_review.py``) hid the hole because its ``_seed`` helper embeds by hand.

The companion half is the alias arm: ``admission._to_observation`` never populated
``Observation.aliases``, so ``_alias_overlap`` (weight 0.10) could never fire for a discovered
candidate even when its normalized name matched an existing entity's stored match-key index
exactly. Both arms are needed to clear the floor, which is why they land together.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityId, new_run_id
from clue_research.discovery_scoring import AdmissionStatus, admit
from clue_research.discovery_scoring.discovery import CandidateHypothesis
from clue_research.discovery_scoring.gate.admission import _to_observation
from clue_research.identity import (
    DEFAULT_EMBEDDER,
    DispositionOutcome,
    Observation,
    backfill_account_embeddings,
    disposition,
    embed_account,
    insert_account_entity,
    list_open_tasks,
    resolve,
    resolve_create_new_entity,
)
from tests._workspace import seed_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_identity_db")


def _candidate(
    *,
    name: str,
    domain: str | None = None,
    record_ref: str = "rec:h1",
    channel: str = "exa",
) -> CandidateHypothesis:
    """A grounded discovery candidate (the M6.1 output the admission gate admits)."""
    return CandidateHypothesis(
        matched_channel=channel,
        source_record_ref=record_ref,
        raw_name=name,
        candidate_domain=domain,
        matched_signal="series-b saas",
        resolver_confidence=0.8,
    )


async def _count_accounts(conn: AsyncConnection) -> int:
    return int((await conn.execute(text("SELECT count(*) FROM account_entity"))).scalar_one())


async def _has_embedding(conn: AsyncConnection, entity_id: EntityId) -> bool:
    row = (
        await conn.execute(
            text("SELECT 1 FROM account_entity_embedding WHERE entity_id = :id"),
            {"id": entity_id},
        )
    ).first()
    return row is not None


def test_discovery_admission_embeds_so_a_name_only_re_encounter_routes_to_review() -> None:
    """The §1.2-H1 scenario end to end: discovery admits a company, then the *same* company is met
    again name-only (no domain) — it must reach the review band, never mint a second entity."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            run_id = new_run_id()
            first = await admit(
                conn,
                _candidate(name="Novaflow Robotics", domain="novaflow.example"),
                run_id,
                workspace_id=ws,
            )
            assert first.status is AdmissionStatus.ADMITTED
            assert first.account_entity_id is not None
            # The admission itself embedded the account — nothing else in the run does.
            assert await _has_embedding(conn, first.account_entity_id)

            before = await _count_accounts(conn)
            second = await admit(
                conn,
                _candidate(name="Novaflow Robotics", record_ref="rec:h1-b", channel="firecrawl"),
                new_run_id(),
                workspace_id=ws,
            )
            assert second.status is AdmissionStatus.NEEDS_REVIEW
            assert second.review_task_id is not None
            assert await _count_accounts(conn) == before  # no silent duplicate
            tasks = await list_open_tasks(conn, workspace_id=ws)
            assert [t.id for t in tasks] == [second.review_task_id]

    run_async(_run())


def test_name_only_re_encounter_clears_the_review_floor_on_both_arms() -> None:
    """The score itself: the cosine arm (embedding) and the alias-overlap arm (admission aliases)
    together put an exact name-only re-encounter in the mid band, not below the floor."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            admitted = await admit(
                conn,
                _candidate(name="Novaflow Robotics", domain="novaflow.example"),
                new_run_id(),
                workspace_id=ws,
            )
            assert admitted.account_entity_id is not None

            observation = _to_observation(_candidate(name="Novaflow Robotics"))
            result = await resolve(conn, observation, workspace_id=ws)
            assert result.top is not None
            assert result.top.entity_id == admitted.account_entity_id
            features = result.top.features
            assert features["name_cosine"] > 0.9  # the embedding exists → the arm is live
            assert features["alias_overlap"] == 1.0  # the admission carried the name as an alias
            assert 0.70 <= result.top_score < 0.95  # the review band, not a new entity

    run_async(_run())


def test_same_name_different_domain_lands_in_the_review_band() -> None:
    """**Band pin.** A candidate whose folded name matches an existing account but whose domain
    does *not* now scores 0.775 — the review band. Before the alias arm fired it scored 0.675 and
    silently minted a second entity; the new behavior is the conservative direction (a human
    decides whether ``apex.io`` and ``apex-corp.com`` are one company), but it is a real band
    move, so it is pinned
    here: a future weight change cannot flip it back to a silent NEW_ENTITY — nor forward into
    auto-merge — without this failing. The scoring itself is deliberately unchanged; whether a
    *conflicting* strong key should veto the name arms is parked for a spec follow-up."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            first = await admit(
                conn,
                _candidate(name="Apex Corp", domain="apex-corp.com"),
                new_run_id(),
                workspace_id=ws,
            )
            assert first.status is AdmissionStatus.ADMITTED

            observation = _to_observation(_candidate(name="Apex Corp", domain="apex.io"))
            result = await resolve(conn, observation, workspace_id=ws)
            assert result.top is not None
            assert result.top.entity_id == first.account_entity_id
            assert result.top.features["domain_agreement"] == 0.0  # the domains genuinely differ
            assert 0.70 <= result.top_score < 0.95  # review — never auto-merged on a name alone

            before = await _count_accounts(conn)
            second = await admit(
                conn,
                _candidate(name="Apex Corp", domain="apex.io", record_ref="rec:h1-apex"),
                new_run_id(),
                workspace_id=ws,
            )
            assert second.status is AdmissionStatus.NEEDS_REVIEW
            assert second.account_entity_id is None  # admits nothing; the human decides
            assert await _count_accounts(conn) == before

    run_async(_run())


def test_review_resolved_new_entity_is_embedded() -> None:
    """The human path mints accounts too, and has no caller that embeds on its behalf — so
    ``resolve_create_new_entity`` embeds by default, or H1 reopens the moment M2.4 composes it."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            await admit(
                conn,
                _candidate(name="Apex Corp", domain="apex-corp.com"),
                new_run_id(),
                workspace_id=ws,
            )
            enqueued = await admit(
                conn,
                _candidate(name="Apex Corp", domain="apex.io", record_ref="rec:h1-apex"),
                new_run_id(),
                workspace_id=ws,
            )
            assert enqueued.status is AdmissionStatus.NEEDS_REVIEW
            assert enqueued.review_task_id is not None

            minted = await resolve_create_new_entity(
                conn, enqueued.review_task_id, resolved_by="reviewer-h1"
            )
            assert await _has_embedding(conn, minted)

    run_async(_run())


def test_admission_observation_carries_the_candidate_name_as_an_alias() -> None:
    """``_to_observation`` populates ``aliases`` (normalized downstream by ``name_key``), so the
    alias-overlap arm can fire; a nameless candidate carries none."""
    assert _to_observation(_candidate(name="Novaflow Robotics")).aliases == ("Novaflow Robotics",)
    assert _to_observation(_candidate(name="", domain="x.example")).aliases == ()


def test_disposition_without_an_embedder_embeds_nothing() -> None:
    """The optional dependency is genuinely optional: a caller that passes no embedder gets exactly
    today's behavior (a new entity, no embedding row) — no new hard requirement on callers."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            obs = Observation(name="Quietwave Systems", domain="quietwave.example")
            result = await resolve(conn, obs, workspace_id=ws)
            decision = await disposition(conn, obs, result, workspace_id=ws)
            assert decision.outcome is DispositionOutcome.NEW_ENTITY
            assert decision.entity_id is not None
            assert not await _has_embedding(conn, decision.entity_id)

    run_async(_run())


def test_disposition_with_an_embedder_embeds_the_new_entity() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            obs = Observation(name="Quietwave Systems", domain="quietwave.example")
            result = await resolve(conn, obs, workspace_id=ws)
            decision = await disposition(
                conn, obs, result, workspace_id=ws, embedder=DEFAULT_EMBEDDER
            )
            assert decision.outcome is DispositionOutcome.NEW_ENTITY
            assert decision.entity_id is not None
            assert await _has_embedding(conn, decision.entity_id)

    run_async(_run())


def test_backfill_embeds_only_the_missing_rows_and_is_idempotent() -> None:
    """The one-shot repair for accounts minted before the fix: embed every unembedded account, skip
    the ones already embedded, and be a no-op on a second pass."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            already = await insert_account_entity(
                conn, canonical_name="Already Embedded", workspace_id=ws
            )
            await embed_account(conn, already)
            missing_a = await insert_account_entity(
                conn, canonical_name="Missing One", workspace_id=ws
            )
            missing_b = await insert_account_entity(
                conn, canonical_name="Missing Two", workspace_id=ws
            )
            stamp = (
                await conn.execute(
                    text("SELECT embedded_at FROM account_entity_embedding WHERE entity_id = :id"),
                    {"id": already},
                )
            ).scalar_one()

            # Scoped to this test's workspace: the predicate is a whole-table scan, so an unscoped
            # pass would also pick up rows a *committing* suite left behind in a shared DB.
            report = await backfill_account_embeddings(conn, workspace_id=ws, batch_size=1)
            assert report.embedded == 2
            assert report.scanned == 2
            assert await _has_embedding(conn, missing_a)
            assert await _has_embedding(conn, missing_b)
            # The already-embedded row was never re-written (not selected, so its stamp stands).
            assert (
                await conn.execute(
                    text("SELECT embedded_at FROM account_entity_embedding WHERE entity_id = :id"),
                    {"id": already},
                )
            ).scalar_one() == stamp

            again = await backfill_account_embeddings(conn, workspace_id=ws)
            assert again.embedded == 0 and again.scanned == 0

    run_async(_run())


def test_backfill_dry_run_counts_what_a_real_pass_would_write() -> None:
    """The preview shares the writing pass's predicate, so it can neither lie nor write."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            missing = await insert_account_entity(
                conn, canonical_name="Unembedded", workspace_id=ws
            )
            embedded = await insert_account_entity(conn, canonical_name="Embedded", workspace_id=ws)
            await embed_account(conn, embedded)

            preview = await backfill_account_embeddings(conn, workspace_id=ws, dry_run=True)
            assert preview.scanned == 1 and preview.embedded == 0
            assert not await _has_embedding(conn, missing)  # a dry run writes nothing

            real = await backfill_account_embeddings(conn, workspace_id=ws)
            assert real.scanned == preview.scanned  # the preview did not under-report
            assert real.embedded == 1

    run_async(_run())


def test_backfill_can_be_scoped_to_one_workspace() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            other = await seed_workspace(conn, "h1-other-workspace")
            mine = await insert_account_entity(conn, canonical_name="Mine", workspace_id=ws)
            theirs = await insert_account_entity(conn, canonical_name="Theirs", workspace_id=other)

            report = await backfill_account_embeddings(conn, workspace_id=ws)
            assert report.embedded == 1
            assert await _has_embedding(conn, mine)
            assert not await _has_embedding(conn, theirs)

    run_async(_run())
