"""M13.2 — DB-backed acceptance criteria for disposition capture (spec §M13.2 AC).

Exercises the real Postgres tables + the ``labeled_dataset`` view against the M13.2 contract:
enum parity; one disposition per review action, idempotent on ``natural_key``; ``ingest_downstream``
resolves-or-rejects (never best-guessed); the provenance snapshot (review-claim + handoff);
``labeled_dataset`` reproducible + append-only with the fit-score join; tombstone drops a contact's
dispositions from the dataset while leaving an audited marker; no CRM in the write path.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    ReviewAction,
    account_claim,
    new_claim_id,
    new_project_run_id,
    new_run_id,
)
from clue_core.enums import AccountStatus
from clue_core.review import ReviewActionOutcome
from clue_research.claimstore import insert_claim
from clue_research.discovery_scoring.scoring.engine import FIT_FIELD
from clue_research.durable.project_run import ensure_project_run
from clue_research.identity import DEFAULT_REUSE_POLICY, insert_account_entity, stamp_reuse
from clue_research.review import (
    DispositionActor,
    DispositionOrigin,
    DispositionStore,
    DispositionType,
    DownstreamOutcome,
    FeedbackDisposition,
    capture_review_action,
    ingest_downstream,
    read_labeled_dataset,
    tombstone_contact_dispositions,
)
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.review.conftest import enum_labels, rollback_conn

pytestmark = pytest.mark.usefixtures("require_review_db")

_CLIENT = "client-acme"
_ICP_KEY = "default"
_ICP_VERSION = 1


def _now() -> datetime:
    return datetime.now(UTC)


# --- seeding helpers (mirror tests/narrative/test_handoff.py) -------------------------------------


async def _account(
    conn: AsyncConnection, *, name: str = "Acme", domain: str | None = None
) -> EntityId:
    await seed_workspace(conn, _CLIENT)
    return await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=domain or f"{name.lower()}.com",
        status=AccountStatus.ACTIVE,
        workspace_id=_CLIENT,
    )


async def _run(conn: AsyncConnection) -> ProjectRunId:
    rid = new_project_run_id()
    await ensure_project_run(
        conn, project_run_id=rid, workspace_id=_CLIENT, icp_key=_ICP_KEY, icp_version=_ICP_VERSION
    )
    return rid


async def _claim(
    conn: AsyncConnection,
    account: EntityId,
    *,
    field_key: str = "core.employee_count",
    value: JsonValue = 500,
    source_key: str = "clay",
) -> ClaimId:
    claim = account_claim(
        entity_id=account,
        field_key=field_key,
        value_json=value,
        source_tier=1,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://src.local/x",
    )
    claim = claim.model_copy(update={"source_key": source_key})
    claim = stamp_reuse(claim, workspace_id=_CLIENT, policy=DEFAULT_REUSE_POLICY)
    return await insert_claim(conn, claim)


async def _fit_score(conn: AsyncConnection, account: EntityId, *, value: float = 0.82) -> ClaimId:
    payload: dict[str, JsonValue] = {
        "value": value,
        "components": [
            {"name": "firmographic", "weight": 1.0, "value": value, "evidence_claim_ids": []}
        ],
        "rubric_version": 1,
        "non_fit_flag": False,
        "fit_floor": 0.3,
        "icp_key": _ICP_KEY,
        "icp_version": _ICP_VERSION,
    }
    claim = account_claim(
        entity_id=account,
        field_key=FIT_FIELD,
        value_json=payload,
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        confidence=1.0,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
    )
    claim = stamp_reuse(claim, workspace_id=_CLIENT, policy=DEFAULT_REUSE_POLICY)
    return await insert_claim(conn, claim)


async def _seed_handoff(
    conn: AsyncConnection, account: EntityId, contributing: Sequence[ClaimId]
) -> None:
    """Materialise a minimal M12.2 ``account_handoff`` whose nested ``provenance_index`` lists the
    contributing claim ids (the shape ``_account_handoff_context`` reads via SQL)."""
    provenance = {
        str(cid): {"source_url": "u", "source_tier": 1, "evidence_span": None}
        for cid in contributing
    }
    payload = {"handoff": {"provenance_index": provenance}}
    await conn.execute(
        text(
            """
            INSERT INTO account_handoff
                (workspace_id, account_entity_id, icp_spec_version, icp_key, assembled_at, payload)
            VALUES (:c, :a, :v, :k, now(), CAST(:p AS jsonb))
            """
        ),
        {"c": _CLIENT, "a": account, "v": _ICP_VERSION, "k": _ICP_KEY, "p": json.dumps(payload)},
    )


async def _count(conn: AsyncConnection, natural_key: str) -> int:
    return int(
        (
            await conn.execute(
                text("SELECT count(*) FROM disposition WHERE natural_key = :n"), {"n": natural_key}
            )
        ).scalar_one()
    )


# --- AC: enum parity ------------------------------------------------------------------------------


def test_disposition_enums_match_python() -> None:
    """The migration's enum labels stay in lock-step with the Python ``StrEnum``s (ordered)."""

    async def go() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            for typname, enum in (
                ("disposition_type", DispositionType),
                ("disposition_actor", DispositionActor),
                ("disposition_origin", DispositionOrigin),
            ):
                assert await enum_labels(conn, typname) == [m.value for m in enum]

    run_async(go())


# --- AC1: one disposition per review action, idempotent on natural_key ----------------------------


def test_review_action_capture_is_idempotent_with_provenance() -> None:
    async def go() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            run = await _run(conn)
            claim = await _claim(conn, account, source_key="clay", field_key="core.employee_count")
            outcome = ReviewActionOutcome(
                action=ReviewAction.APPROVE, claim_id=claim, review_action_id=uuid4()
            )

            did = await capture_review_action(
                conn,
                outcome,
                account_entity_id=account,
                contact_entity_id=None,
                project_run_id=run,
                actor="alice",
            )

            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT disposition_type, entity_id, account_entity_id, workspace_id, "
                            "icp_key, icp_spec_version, claim_id, origin, actor, natural_key "
                            "FROM disposition WHERE id = :i"
                        ),
                        {"i": did},
                    )
                )
                .mappings()
                .one()
            )
            assert row["disposition_type"] == "claim_approved"
            assert row["workspace_id"] == _CLIENT
            assert row["icp_key"] == _ICP_KEY and row["icp_spec_version"] == _ICP_VERSION
            assert EntityId(row["account_entity_id"]) == account
            assert ClaimId(row["claim_id"]) == claim
            assert row["origin"] == "review_surface" and row["actor"] == "internal_reviewer"
            assert row["natural_key"] == f"review_surface:{outcome.review_action_id}"

            prov = (
                (
                    await conn.execute(
                        text(
                            "SELECT contributing_source_keys s, contributing_field_keys f, "
                            "contributing_claim_ids c "
                            "FROM disposition_provenance WHERE disposition_id = :i"
                        ),
                        {"i": did},
                    )
                )
                .mappings()
                .one()
            )
            assert list(prov["s"]) == ["clay"]
            assert list(prov["f"]) == ["core.employee_count"]
            assert list(prov["c"]) == [str(claim)]

            # replay the same action — same disposition id, still exactly one row.
            again = await capture_review_action(
                conn,
                outcome,
                account_entity_id=account,
                contact_entity_id=None,
                project_run_id=run,
                actor="alice",
            )
            assert again == did
            assert await _count(conn, row["natural_key"]) == 1

    run_async(go())


# --- AC2: ingest_downstream resolves-or-rejects, never best-guessed; idempotent -------------------


def test_ingest_downstream_resolves_or_rejects_and_dedupes() -> None:
    async def go() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn, name="Acme", domain="acme.com")
            pre_resolved = DownstreamOutcome(
                external_id="op-1",
                disposition_type=DispositionType.ACCOUNT_ACCEPTED,
                workspace_id=_CLIENT,
                occurred_at=_now(),
                account_entity_id=account,
            )
            by_domain = DownstreamOutcome(
                external_id="op-2",
                disposition_type=DispositionType.REPLY_RECEIVED,
                workspace_id=_CLIENT,
                occurred_at=_now(),
                company_name="Acme Inc",
                domain="acme.com",
            )
            unresolvable = DownstreamOutcome(
                external_id="op-3",
                disposition_type=DispositionType.ACCOUNT_REJECTED,
                workspace_id=_CLIENT,
                occurred_at=_now(),
                company_name="Ghost Co",
                domain="ghost-co.invalid",
            )

            report = await ingest_downstream(conn, [pre_resolved, by_domain, unresolvable])
            assert len(report.recorded) == 2
            assert len(report.rejected) == 1
            assert report.rejected[0].external_id == "op-3"
            assert report.rejected[0].reason == "unresolved"

            # op-2's free-text name+domain resolved to the *same* account as the pre-resolved op-1.
            resolved = {
                EntityId(r["account_entity_id"])
                for r in (
                    await conn.execute(
                        text(
                            "SELECT account_entity_id FROM disposition WHERE origin = 'crm_ingest'"
                        )
                    )
                )
                .mappings()
                .all()
            }
            assert resolved == {account}

            # the unresolvable company never wrote a row (no best-guess).
            assert await _count(conn, "crm_ingest:client-acme:op-3:account_rejected") == 0

            # idempotent replay of op-1 → same id, still one row.
            replay = await ingest_downstream(conn, [pre_resolved])
            assert len(replay.recorded) == 1
            assert await _count(conn, "crm_ingest:client-acme:op-1:account_accepted") == 1

    run_async(go())


# --- AC3: account-level provenance snapshot from the persisted handoff, stable --------------------


def test_account_disposition_snapshots_handoff_provenance() -> None:
    async def go() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            c1 = await _claim(
                conn, account, field_key="core.employee_count", value=500, source_key="clay"
            )
            c2 = await _claim(
                conn,
                account,
                field_key="core.primary_domain",
                value="acme.com",
                source_key="builtwith",
            )
            await _seed_handoff(conn, account, [c1, c2])

            report = await ingest_downstream(
                conn,
                [
                    DownstreamOutcome(
                        external_id="won-1",
                        disposition_type=DispositionType.CLOSED_WON,
                        workspace_id=_CLIENT,
                        occurred_at=_now(),
                        account_entity_id=account,
                    )
                ],
            )
            did = report.recorded[0]

            # ICP context was backfilled from the latest handoff (the row carried none).
            ctx = (
                (
                    await conn.execute(
                        text("SELECT icp_key, icp_spec_version FROM disposition WHERE id = :i"),
                        {"i": did},
                    )
                )
                .mappings()
                .one()
            )
            assert ctx["icp_key"] == _ICP_KEY and ctx["icp_spec_version"] == _ICP_VERSION

            prov = (
                (
                    await conn.execute(
                        text(
                            "SELECT contributing_source_keys s, contributing_field_keys f, "
                            "contributing_claim_ids c "
                            "FROM disposition_provenance WHERE disposition_id = :i"
                        ),
                        {"i": did},
                    )
                )
                .mappings()
                .one()
            )
            assert set(prov["s"]) == {"clay", "builtwith"}
            assert set(prov["f"]) == {"core.employee_count", "core.primary_domain"}
            assert set(prov["c"]) == {str(c1), str(c2)}

    run_async(go())


# --- AC4 + AC5: labeled_dataset reproducible + append-only; tombstone removes contact rows --------


def test_labeled_dataset_joins_score_is_reproducible_and_tombstone_aware() -> None:
    async def go() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            run = await _run(conn)
            await _fit_score(conn, account, value=0.82)
            claim = await _claim(conn, account, source_key="clay")

            # an account-keyed review disposition + a contact-keyed one (same account).
            account_action = ReviewActionOutcome(
                action=ReviewAction.APPROVE, claim_id=claim, review_action_id=uuid4()
            )
            account_did = await capture_review_action(
                conn,
                account_action,
                account_entity_id=account,
                contact_entity_id=None,
                project_run_id=run,
                actor="bob",
            )
            contact = EntityId(uuid4())
            contact_action = ReviewActionOutcome(
                action=ReviewAction.CORRECT,
                claim_id=claim,
                review_action_id=uuid4(),
                superseding_claim_id=new_claim_id(),
            )
            await capture_review_action(
                conn,
                contact_action,
                account_entity_id=account,
                contact_entity_id=contact,
                project_run_id=run,
                actor="bob",
            )

            rows = await read_labeled_dataset(
                conn, workspace_id=_CLIENT, icp_spec_version=_ICP_VERSION, icp_key=_ICP_KEY
            )
            assert len(rows) == 2
            by_id = {r.disposition_id: r for r in rows}
            acct_row = by_id[account_did]
            assert isinstance(acct_row.fit_score_json, dict)
            assert acct_row.fit_score_json["value"] == 0.82
            assert acct_row.contributing_field_keys == ("core.employee_count",)

            # reproducible: re-running yields the same row identities.
            again = await read_labeled_dataset(
                conn, workspace_id=_CLIENT, icp_spec_version=_ICP_VERSION, icp_key=_ICP_KEY
            )
            assert {r.disposition_id for r in again} == set(by_id)

            # tombstone the contact → its (contact-keyed) disposition leaves the dataset; the
            # account-keyed one stays; both rows remain on the table (audited, not deleted).
            stamped = await tombstone_contact_dispositions(conn, contact)
            assert stamped == 1
            after = await read_labeled_dataset(conn, workspace_id=_CLIENT)
            assert [r.disposition_id for r in after] == [account_did]
            total = (await conn.execute(text("SELECT count(*) FROM disposition"))).scalar_one()
            assert total == 2

    run_async(go())


# --- the store class path (conn_factory) + no CRM in the write path -------------------------------


@asynccontextmanager
async def _static(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    """A conn_factory that hands the store the test's rolled-back connection (no commit/close)."""
    yield conn


def test_store_class_record_and_labeled_dataset() -> None:
    async def go() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            run = await _run(conn)
            store = DispositionStore(conn_factory=lambda: _static(conn))
            disposition = FeedbackDisposition.for_downstream(
                disposition_type=DispositionType.ACCOUNT_ACCEPTED,
                account_entity_id=account,
                workspace_id=_CLIENT,
                external_id="x1",
                occurred_at=_now(),
                icp_key=_ICP_KEY,
                icp_spec_version=_ICP_VERSION,
                project_run_id=run,
            )
            did = await store.record(disposition)
            rows = await store.labeled_dataset(workspace_id=_CLIENT)
            assert did in {r.disposition_id for r in rows}

    run_async(go())
