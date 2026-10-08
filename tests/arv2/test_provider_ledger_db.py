"""Draining the buffered sinks: artifacts for the raw bodies, rows in ``provider_call_ledger``."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import text

from clue_agents.contracts import ArtifactRef
from clue_api.arv2.provider_ledger import (
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.sinks import LedgerRow, RawRecord, RawRequest, RawResponse, sha256_hex
from clue_api.provider_incidents import open_incidents
from clue_core import decode_jsonb

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class FakeArtifacts:
    """The artifact-sink shape the fleet composes, without the storage backend behind it."""

    def __init__(self) -> None:
        self.bodies: list[bytes] = []

    async def persist_body(self, *, workspace_id: str, data: bytes, media_type: str) -> ArtifactRef:
        self.bodies.append(data)
        digest = hashlib.sha256(data).hexdigest()
        return ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=f"art/{digest}",
            sha256=digest,
            media_type=media_type,
            byte_count=len(data),
        )


def _record(body: bytes) -> RawRecord:
    return RawRecord(
        call_id="7b1c2e4a-0f3d-4c7e-9a1b-2d3e4f5a6b7c",
        provider="exa",
        operation="search",
        label="account:zafran.io",
        attempt=1,
        recorded_at=NOW,
        latency_ms=5,
        request=RawRequest(
            method="POST",
            url="https://api.exa.ai/search",
            headers={},
            body_text='{"q":1}',
            body_sha256=sha256_hex(b'{"q":1}'),
            body_bytes=7,
        ),
        response=RawResponse(
            status=200,
            headers={},
            body_text=body.decode(),
            body_sha256=sha256_hex(body),
            body_bytes=len(body),
        ),
    )


def _result_row(*, row_id: str, call_id: str, raw_ref: str | None) -> LedgerRow:
    return LedgerRow(
        row_id=row_id,
        call_id=call_id,
        phase="result",
        provider="exa",
        operation="search",
        label="account:zafran.io",
        recorded_at=NOW,
        http_status=200,
        latency_ms=5,
        attempts=1,
        cost_usd=Decimal("0.007"),
        credits=Decimal("2.5"),
        media_seconds=11,
        outcome="ok",
        raw_ref=raw_ref,
        extras={"costDollars": {"total": 0.007}},
    )


def _stamp(job_id: UUID) -> LedgerStamp:
    return LedgerStamp(
        workspace_id="ws_arv2",
        project_id="prj_arv2",
        project_run_id=str(uuid4()),
        job_id=job_id,
    )


def test_drain_writes_ledger_rows_with_artifact_keys_and_extras() -> None:
    call_id = "7b1c2e4a-0f3d-4c7e-9a1b-2d3e4f5a6b7c"
    job_id = uuid4()

    async def scenario():  # type: ignore[no-untyped-def]
        raw, ledger = BufferedRawSink(), BufferedLedger()
        artifacts = FakeArtifacts()
        ref = raw.save(_record(b'{"ok":true}'), b'{"ok":true}')
        ledger.record(
            LedgerRow(
                row_id="r0",
                call_id=call_id,
                phase="estimate",
                provider="exa",
                operation="search",
                label="account:zafran.io",
                recorded_at=NOW,
                estimate_usd=Decimal("0.01"),
                estimate_credits=Decimal("1"),
                estimate_media_seconds=3,
            )
        )
        ledger.record(_result_row(row_id="r1", call_id=call_id, raw_ref=ref))
        stamp = _stamp(job_id)
        async with rollback_conn(seed_pack=False) as conn:
            report = await drain_provider_calls(
                conn, raw=raw, ledger=ledger, artifacts=artifacts, stamp=stamp
            )
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT ledger_id, phase, response_artifact_key, extras_json, "
                            " entity_research_job_id, workspace_id, project_id, project_run_id, "
                            " cost_usd, credits, media_seconds, estimate_usd, over_ceiling, "
                            " outcome, attempts, http_status, latency_ms, recorded_at "
                            "FROM provider_call_ledger WHERE call_id = :c ORDER BY phase"
                        ),
                        {"c": call_id},
                    )
                )
                .mappings()
                .all()
            )
        return report, [dict(row) for row in rows], stamp, artifacts.bodies

    report, rows, stamp, bodies = run_async(scenario())

    # Only the ``result`` phase is spend; the estimate row is a reservation.
    assert report.rows == 2
    assert report.artifacts == 1
    assert report.cost_usd == Decimal("0.007")
    assert report.credits == Decimal("2.5")
    assert report.media_seconds == 11
    assert len(bodies) == 1 and b'"body_utf8": "{\\"ok\\":true}"' in bodies[0]

    estimate, result = rows
    assert estimate["phase"] == "estimate"
    assert estimate["response_artifact_key"] is None
    assert estimate["estimate_usd"] == Decimal("0.010000")
    assert estimate["ledger_id"] == uuid5(NAMESPACE_URL, "arv2-ledger:r0")

    assert result["response_artifact_key"].startswith("art/")
    assert decode_jsonb(result["extras_json"]) == {"costDollars": {"total": 0.007}}
    assert result["entity_research_job_id"] == stamp.job_id
    assert result["workspace_id"] == stamp.workspace_id
    assert result["project_id"] == stamp.project_id
    assert result["project_run_id"] == stamp.project_run_id
    assert result["cost_usd"] == Decimal("0.007000")
    assert result["credits"] == Decimal("2.500")
    assert result["media_seconds"] == 11
    assert result["outcome"] == "ok"
    assert result["attempts"] == 1
    assert result["http_status"] == 200
    assert result["latency_ms"] == 5
    assert result["over_ceiling"] is False
    assert result["recorded_at"] == NOW


def test_a_foreign_call_id_is_derived_and_a_redrain_inserts_nothing_twice() -> None:
    """R1 mints a uuid; anything else is content-addressed, and the drain stays idempotent."""

    async def scenario():  # type: ignore[no-untyped-def]
        stamp = _stamp(uuid4())
        async with rollback_conn(seed_pack=False) as conn:
            counts = []
            for _ in range(2):
                ledger = BufferedLedger()
                ledger.record(_result_row(row_id="r-dup", call_id="not-a-uuid", raw_ref=None))
                await drain_provider_calls(
                    conn,
                    raw=BufferedRawSink(),
                    ledger=ledger,
                    artifacts=FakeArtifacts(),
                    stamp=stamp,
                )
                counts.append(
                    (
                        await conn.execute(
                            text("SELECT count(*) FROM provider_call_ledger WHERE call_id = :c"),
                            {"c": uuid5(NAMESPACE_URL, "not-a-uuid")},
                        )
                    ).scalar_one()
                )
        return counts

    assert run_async(scenario()) == [1, 1]


def test_a_workspace_only_stamp_lands_null_project_run_and_job() -> None:
    """Slice 1b: a display page or a chat-turn tool has no project, run or job to stamp — the
    row is workspace spend, and the three columns say so with NULL rather than a placeholder."""

    async def scenario():  # type: ignore[no-untyped-def]
        ledger = BufferedLedger()
        ledger.record(_result_row(row_id="r-ws-only", call_id=str(uuid4()), raw_ref=None))
        async with rollback_conn(seed_pack=False) as conn:
            await drain_provider_calls(
                conn,
                raw=BufferedRawSink(),
                ledger=ledger,
                artifacts=FakeArtifacts(),
                stamp=LedgerStamp(workspace_id="ws_only"),
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT workspace_id, project_id, project_run_id, entity_research_job_id "
                        "FROM provider_call_ledger WHERE ledger_id = :id"
                    ),
                    {"id": uuid5(NAMESPACE_URL, "arv2-ledger:r-ws-only")},
                )
            ).one()
        return tuple(row)

    assert run_async(scenario()) == ("ws_only", None, None, None)


def _incident_row(
    provider: str,
    *,
    status: int,
    extras: dict[str, object],
    label: str = "round-1",
    operation: str = "agent_completion",
    recorded_at: datetime = NOW,
) -> LedgerRow:
    return LedgerRow(
        row_id=str(uuid4()),
        call_id=str(uuid4()),
        phase="result",
        provider=provider,
        operation=operation,
        label=label,
        recorded_at=recorded_at,
        http_status=status,
        latency_ms=10,
        attempts=1,
        cost_usd=Decimal(0),
        outcome="ok" if status < 400 else "client_error",
        extras=extras,
    )


def test_the_drain_opens_an_incident_from_a_stamped_refusal_and_closes_it_on_a_later_success() -> (
    None
):
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            stamp = LedgerStamp(
                workspace_id="ws_drain",
                project_id="prj_1",
                project_run_id=str(uuid4()),
                job_id=uuid4(),
            )
            ledger = BufferedLedger()
            ledger.record(
                _incident_row(
                    "openrouter",
                    status=403,
                    extras={
                        "provider_failure": {
                            "kind": "refusal",
                            "reason": "key_limit",
                            "message": "Key limit exceeded",
                        },
                        "cost_source": "unpriced",
                    },
                )
            )
            await drain_provider_calls(
                conn, raw=BufferedRawSink(), ledger=ledger, artifacts=FakeArtifacts(), stamp=stamp
            )
            (incident,) = await open_incidents(conn, providers=["openrouter"])
            assert incident.reason == "key_limit" and incident.surfaces == {"research_job": 1}
            ledger.record(
                _incident_row("openrouter", status=200, extras={"cost_source": "metered"})
            )
            await drain_provider_calls(
                conn, raw=BufferedRawSink(), ledger=ledger, artifacts=FakeArtifacts(), stamp=stamp
            )
            assert await open_incidents(conn, providers=["openrouter"]) == ()

    run_async(scenario())


def test_the_drain_counts_failures_toward_the_threshold_across_drains() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            stamp = LedgerStamp(workspace_id="ws_drain", project_run_id=str(uuid4()))
            failure_extras: dict[str, object] = {
                "provider_failure": {
                    "kind": "failure",
                    "reason": "server_error",
                    "message": "503",
                },
                "cost_source": "estimate",
            }
            for _ in range(2):
                ledger = BufferedLedger()
                ledger.record(
                    _incident_row(
                        "exa",
                        status=503,
                        operation="answer",
                        label="discovery:x",
                        extras=failure_extras,
                    )
                )
                await drain_provider_calls(
                    conn,
                    raw=BufferedRawSink(),
                    ledger=ledger,
                    artifacts=FakeArtifacts(),
                    stamp=stamp,
                )
            assert await open_incidents(conn, providers=["exa"]) == ()
            ledger = BufferedLedger()
            ledger.record(
                _incident_row(
                    "exa",
                    status=503,
                    operation="answer",
                    label="discovery:y",
                    extras=failure_extras,
                )
            )
            await drain_provider_calls(
                conn, raw=BufferedRawSink(), ledger=ledger, artifacts=FakeArtifacts(), stamp=stamp
            )
            (incident,) = await open_incidents(conn, providers=["exa"])
            assert incident.kind == "failure" and incident.surfaces == {"discovery": 1}

    run_async(scenario())


REFUSAL_EXTRAS: dict[str, object] = {
    "provider_failure": {
        "kind": "refusal",
        "reason": "credits_exhausted",
        "message": "payment_required",
    },
    "cost_source": "unpriced",
}


def test_an_ok_row_earlier_in_the_batch_than_the_refusal_does_not_close_the_incident() -> None:
    """A drain is a whole hop: two hundred good rows and then the 402 that stopped it. The
    provider's *last* word in the batch decides, so that batch ends open, not opened-and-closed."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            stamp = LedgerStamp(workspace_id="ws_drain", project_run_id=str(uuid4()))
            ledger = BufferedLedger()
            ledger.record(
                _incident_row(
                    "exa_websets",
                    status=200,
                    operation="websets:get",
                    extras={"cost_source": "metered"},
                )
            )
            ledger.record(
                _incident_row(
                    "exa_websets",
                    status=402,
                    operation="websets:create",
                    extras=REFUSAL_EXTRAS,
                    recorded_at=NOW + timedelta(seconds=1),
                )
            )
            await drain_provider_calls(
                conn, raw=BufferedRawSink(), ledger=ledger, artifacts=FakeArtifacts(), stamp=stamp
            )
            (incident,) = await open_incidents(conn, providers=["exa_websets"])
            assert incident.reason == "credits_exhausted"

            ledger = BufferedLedger()
            ledger.record(
                _incident_row(
                    "exa_websets",
                    status=200,
                    operation="websets:get",
                    extras={"cost_source": "metered"},
                    recorded_at=NOW + timedelta(seconds=2),
                )
            )
            await drain_provider_calls(
                conn, raw=BufferedRawSink(), ledger=ledger, artifacts=FakeArtifacts(), stamp=stamp
            )
            assert await open_incidents(conn, providers=["exa_websets"]) == ()

    run_async(scenario())


def test_an_onboarding_row_counts_as_onboarding_even_though_it_stamps_a_job_id() -> None:
    """Slice 1b: an onboarding run stamps its own id as the job, so the label has to be read first
    or the onboarding surface would never appear in an incident's breakdown."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            stamp = LedgerStamp(workspace_id="ws_drain", job_id=uuid4())
            ledger = BufferedLedger()
            ledger.record(
                _incident_row(
                    "openrouter",
                    status=402,
                    label="onboarding-recon",
                    extras=REFUSAL_EXTRAS,
                )
            )
            await drain_provider_calls(
                conn, raw=BufferedRawSink(), ledger=ledger, artifacts=FakeArtifacts(), stamp=stamp
            )
            (incident,) = await open_incidents(conn, providers=["openrouter"])
            assert incident.surfaces == {"onboarding": 1}

    run_async(scenario())


def test_a_held_drain_stores_its_bodies_first_and_records_its_rows_later() -> None:
    """W2-15 option B: the raw bodies are stored before the worker's database lock is taken; the
    rows are written later, inside the locked transaction, citing those bodies — once."""
    from clue_api.arv2.provider_ledger import hold_drain

    call_id = "5d0c7f21-6a8b-4e3c-9f10-1b2c3d4e5f60"
    job_id = uuid4()

    async def scenario():  # type: ignore[no-untyped-def]
        raw, ledger = BufferedRawSink(), BufferedLedger()
        artifacts = FakeArtifacts()
        ref = raw.save(_record(b'{"ok":true}'), b'{"ok":true}')
        ledger.record(_result_row(row_id="held-r1", call_id=call_id, raw_ref=ref))
        stamp = _stamp(job_id)
        held = await hold_drain(raw=raw, ledger=ledger, artifacts=artifacts, stamp=stamp)
        assert len(artifacts.bodies) == 1 and held.raw_artifact_keys[ref].startswith("art/")
        assert [r.row_id for r in held.result_rows] == ["held-r1"]
        async with rollback_conn(seed_pack=False) as conn:
            report = await drain_provider_calls(
                conn, raw=raw, ledger=ledger, artifacts=artifacts, stamp=stamp, held=held
            )
            cited = (
                await conn.execute(
                    text("SELECT response_artifact_key FROM provider_call_ledger WHERE call_id=:c"),
                    {"c": call_id},
                )
            ).scalar_one()
        return report, cited, held, artifacts.bodies

    report, cited, held, bodies = run_async(scenario())
    assert len(bodies) == 1  # stored once, before the rows
    assert report.rows == 1 and report.artifacts == 1
    assert cited == next(iter(held.raw_artifact_keys.values()))
    assert report.raw_bodies == held.raw_bodies
