"""``GET /frontend/v1/projects/{id}/research/progress`` — the pinned card's document.

One project, one launched run, two account jobs — the shape the card is actually drawn from.
The walk is the card's whole life: nothing launched yet (``null``, so the frontend draws no
card), one job claimed and stamped ``synthesis`` (a running card with its live agent row), then
that job failing into ``needs_review`` (the attention pill, with the driver's own failure text),
and finally that same run aged a day (ruling R11: nothing moves a job out of ``needs_review`` and
the card has no dismiss control, so the attention clause is time-bounded and the card goes away).
Workspace scoping is asserted the way the sibling discovery-status test asserts it: another
tenant's header never sees this project's run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_store import begin_job, list_jobs, set_job_stage
from clue_api.frontend_read.app import FRONTEND_READ_PREFIX
from clue_api.provider_incidents import record_failure
from clue_core.provider_failures import ProviderFailure
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import FakeQueue, seed_icp_fixture
from tests.arv2.test_account_research_launch_db import _launch, _request
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

from .test_frontend_read_accounts_list import _app, _client

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

#: The two accounts ``seed_icp_fixture`` inserts, in the order it inserts them.
FIRST_ACCOUNT = "Probook"


def test_null_then_running_then_needs_attention_then_aged_out(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            path = f"{FRONTEND_READ_PREFIX}/projects/{fixture.project_id}/research/progress"
            headers = {"X-Workspace-Id": fixture.workspace_id}

            # Nothing launched yet: no run, so no card at all.
            async with _client(_app(conn)) as client:
                empty = await client.get(path, headers=headers)
            assert empty.status_code == 200 and empty.json()["data"] is None

            receipt = await _launch(conn, storage, _request(fixture), FakeQueue())
            jobs = {
                job.account_entity_id: job.job_id
                for job in await list_jobs(conn, run_id=receipt.run_id)
            }
            assert len(jobs) == 2
            first = jobs[UUID(str(fixture.accounts[0]))]
            assert await begin_job(conn, job_id=first) is not None
            await set_job_stage(conn, job_id=first, stage="synthesis")

            async with _client(_app(conn)) as client:
                live = await client.get(path, headers=headers)
                other = await client.get(path, headers={"X-Workspace-Id": "ws_someone_else"})
            body = live.json()["data"]
            counts = (body["requested_accounts"], body["queued"], body["running"], body["finished"])
            assert counts == (2, 1, 1, 0)
            # Half-up of the two accounts' mean (0.25 + 0) / 2 = 12.5 %.
            assert body["progress_pct"] == 13
            assert body["pill"] == "running"
            assert body["agents"] == [
                {
                    "account_name": FIRST_ACCOUNT,
                    "stage": "synthesis",
                    "subject": "account",
                    "subject_name": None,
                }
            ]
            assert body["attention"] == []
            assert body["last_finished_at"] is None
            # Another workspace never sees this project's run.
            assert other.status_code in (200, 404)
            if other.status_code == 200:
                assert other.json()["data"] is None

            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET status = 'needs_review', "
                    "failure_code = 'model_error', failure_message = 'the model errored', "
                    "finished_at = now() WHERE job_id = :id"
                ),
                {"id": first},
            )
            async with _client(_app(conn)) as client:
                attention = await client.get(path, headers=headers)
            body = attention.json()["data"]
            assert body["pill"] == "needs_attention"
            assert body["attention"] == [
                {"account_name": FIRST_ACCOUNT, "reason": "the model errored"}
            ]
            assert body["agents"] == []
            assert body["last_finished_at"] is not None

            # Ruling R11: a day later the whole run is settled and the attention has aged out —
            # the card is gone rather than pinned above the composer forever. (The run's other job
            # is finished too, because a single unfinished job keeps its run loaded on its own.)
            await conn.execute(
                text(
                    "UPDATE arv2_research_job "
                    "SET status = 'completed', finished_at = now() - interval '25 hours' "
                    "WHERE run_id = :run AND job_id <> :id"
                ),
                {"run": receipt.run_id, "id": first},
            )
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET finished_at = now() - interval '25 hours' "
                    "WHERE job_id = :id"
                ),
                {"id": first},
            )
            async with _client(_app(conn)) as client:
                aged = await client.get(path, headers=headers)
            assert aged.status_code == 200 and aged.json()["data"] is None

    run_async(scenario())


def test_a_refused_job_shows_the_incident_and_the_card_names_the_provider(tmp_path: Any) -> None:
    """A job killed by a provider refusal reads as the shared sentence, and the card carries the
    open incident the operator can act on (design 2026-09-16 §3.3)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            path = f"{FRONTEND_READ_PREFIX}/projects/{fixture.project_id}/research/progress"
            headers = {"X-Workspace-Id": fixture.workspace_id}
            receipt = await _launch(conn, storage, _request(fixture), FakeQueue())
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET status = 'needs_review', "
                    "failure_code = 'provider_refused:openrouter:key_limit', "
                    "failure_message = 'Key limit exceeded', finished_at = now() "
                    "WHERE run_id = :run"
                ),
                {"run": receipt.run_id},
            )
            await record_failure(
                conn,
                ProviderFailure("openrouter", "refusal", "key_limit", "Key limit exceeded"),
                surface="research_job",
                workspace_id=fixture.workspace_id,
                now=datetime.now(UTC),
            )

            async with _client(_app(conn)) as client:
                body = (await client.get(path, headers=headers)).json()["data"]

            assert body["pill"] == "needs_attention"
            assert body["attention"][0]["reason"].startswith(
                "Model provider refused: key limit exceeded. Since "
            )
            incident = body["incident"]
            assert incident is not None
            assert incident["provider_label"] == "Model provider"
            assert incident["reason_label"] == "key limit exceeded"
            assert incident["affected"] == 1
            assert incident["notified"] is False
            assert incident["since"]

    run_async(scenario())


def test_a_card_with_no_provider_incident_carries_none(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            path = f"{FRONTEND_READ_PREFIX}/projects/{fixture.project_id}/research/progress"
            headers = {"X-Workspace-Id": fixture.workspace_id}
            receipt = await _launch(conn, storage, _request(fixture), FakeQueue())
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET status = 'needs_review', "
                    "failure_code = 'model_error', failure_message = 'the model errored', "
                    "finished_at = now() WHERE run_id = :run"
                ),
                {"run": receipt.run_id},
            )
            async with _client(_app(conn)) as client:
                body = (await client.get(path, headers=headers)).json()["data"]
            assert body["attention"][0]["reason"] == "the model errored"
            assert body["incident"] is None

    run_async(scenario())
