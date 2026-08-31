"""A3 (defect R3-D) — `POST /agent/runs/{run_id}/cancel`, the durable half.

THE DEFECT. `.context/w5-apollo-e2e-report.md` §R3.7: "no cancel surface for an in-flight agent
turn" — a doomed manual-reference run had to be watched to completion because nothing could ask
it to stop. `apps/agent_runtime/tests/test_cancellation.py` proves the runtime STOPS; this file
proves the request is DURABLE and honest, against real Postgres.

WHY DURABILITY IS THE point AND NOT AN EXTRA. The human asks on a web process; the run is driven
by a fleet worker in another process (detached) or another thread (embedded). They share nothing
but the database. An in-memory flag would be invisible across that gap and would evaporate on a
worker restart or a lease takeover — and a takeover re-runs the same frozen envelope, so a
cancellation that did not survive it would silently un-cancel the run. The restart test below is
that guarantee, stated as the exact shape that would have broken it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client, unique_run_id

from lumen_api.design_store import HybridRepository
from lumen_api.main import _run_cancel_probe, create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache"))


# --- the route's three honest answers -----------------------------------------------------


def test_cancelling_an_unknown_run_is_404(client: TestClient) -> None:
    """Fail-closed, and indistinguishable from a cross-tenant run — the posture the run snapshot
    and the stream-token mint already hold. A refusal that leaked existence would make this route
    an oracle for which run ids are real."""
    assert client.post("/agent/runs/run_never_created/cancel").status_code == 404


def test_cancelling_a_live_run_stamps_it_and_says_so(client: TestClient) -> None:
    run_id = unique_run_id("cancel")
    HybridRepository().create_run(run_id, None)

    response = client.post(f"/agent/runs/{run_id}/cancel")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == run_id
    assert body["cancellation"] == "requested"
    assert body["cancel_requested_at"] is not None
    # The request is NOT the outcome. The driving worker owns the terminal write; announcing one
    # here would be a guess that races the only writer entitled to make it.
    assert body["status"] == "queued"


def test_cancelling_twice_is_idempotent_and_keeps_the_first_timestamp(
    client: TestClient,
) -> None:
    """"When was this cancelled" must keep answering the same thing however many times the button
    is pressed. A second ask is not a second cancellation."""
    run_id = unique_run_id("cancel2")
    HybridRepository().create_run(run_id, None)

    first = client.post(f"/agent/runs/{run_id}/cancel").json()
    second = client.post(f"/agent/runs/{run_id}/cancel").json()

    assert first["cancellation"] == "requested"
    assert second["cancellation"] == "already_requested"
    assert second["cancel_requested_at"] == first["cancel_requested_at"]


def test_cancelling_a_terminal_run_is_an_honest_no_op(client: TestClient) -> None:
    """A human racing a run that ended a second ago has done nothing wrong.

    Deliberately 200-with-the-truth rather than a refusal: a 4xx here would only invite a retry
    loop against a row that will never move again, and the caller's real question — "is it still
    going?" — is answered by `cancellation: already_terminal` plus the status.
    """
    run_id = unique_run_id("cancel3")
    repo = HybridRepository()
    repo.create_run(run_id, None)
    repo.complete_run(run_id, "succeeded", {"status": "applied"}, "result", {"status": "applied"})

    body = client.post(f"/agent/runs/{run_id}/cancel").json()

    assert body["cancellation"] == "already_terminal"
    assert body["cancel_requested_at"] is None
    assert body["status"] == "succeeded"
    # And the terminal result is untouched — a late cancel never rewrites a real outcome.
    assert client.get(f"/agent/runs/{run_id}").json()["result"] == {"status": "applied"}


def test_a_cancel_never_moves_the_run_status_itself(client: TestClient) -> None:
    """The status column has exactly one writer while a lease is live: the worker.

    Stamping a terminal status from the route would race it and could overwrite a real result
    with a guess — the same reason the route's body reports the CURRENT status rather than a
    predicted one.
    """
    run_id = unique_run_id("cancel4")
    HybridRepository().create_run(run_id, None)

    client.post(f"/agent/runs/{run_id}/cancel")

    assert client.get(f"/agent/runs/{run_id}").json()["status"] == "queued"


def test_a_cancel_is_workspace_scoped(tmp_path: Path) -> None:
    """One tenant cannot stop another tenant's run, and learns nothing by trying."""
    owner = make_client(create_app(tmp_path / "engine-cache"))
    run_id = unique_run_id("cancel5")
    HybridRepository().create_run(run_id, None)

    intruder = make_client(create_app(tmp_path / "engine-cache-2"))
    intruder.headers["X-Workspace-Id"] = "ws_someone_else"

    assert intruder.post(f"/agent/runs/{run_id}/cancel").status_code == 404
    # Untouched for its owner: the refusal wrote nothing.
    assert owner.post(f"/agent/runs/{run_id}/cancel").json()["cancellation"] == "requested"


# --- durability: the whole reason this is a row -------------------------------------------


def test_the_request_survives_a_worker_restart(tmp_path: Path) -> None:
    """THE point. A cancel set before a restart is still a cancel after one.

    The shape that would have broken here is the real one: a worker dies mid-turn, its lease
    expires, a takeover worker re-claims the run and redrives it from the same frozen envelope.
    A cancellation held anywhere but the row would be gone by then and the takeover would happily
    re-run the doomed turn. So the probe is rebuilt from scratch — a NEW repository over the same
    database, which is exactly what a restarted worker holds — and must still answer True.
    """
    cancelling = make_client(create_app(tmp_path / "engine-cache"))
    run_id = unique_run_id("restart")
    HybridRepository().create_run(run_id, None)

    assert cancelling.post(f"/agent/runs/{run_id}/cancel").json()["cancellation"] == "requested"
    del cancelling

    # "Restart": nothing in memory carries over; only Postgres does.
    fresh_worker_store = HybridRepository()
    probe = _run_cancel_probe(fresh_worker_store, run_id)

    assert probe() is True


def test_an_uncancelled_run_probes_false(tmp_path: Path) -> None:
    """The negative case, so the assertion above cannot pass vacuously."""
    make_client(create_app(tmp_path / "engine-cache"))
    run_id = unique_run_id("uncancelled")
    store = HybridRepository()
    store.create_run(run_id, None)

    assert _run_cancel_probe(store, run_id)() is False


def test_the_probe_of_a_vanished_run_is_false_not_an_explosion(tmp_path: Path) -> None:
    """The probe is consulted from inside a synchronous turn body, where a raise would become the
    run's cause of death instead of its stop signal. A run that is not there is not a cancel."""
    make_client(create_app(tmp_path / "engine-cache"))
    store = HybridRepository()

    assert _run_cancel_probe(store, unique_run_id("ghost"))() is False


# --- the route table ------------------------------------------------------------------------


def test_the_cancel_route_exists_and_demands_the_workspace_seam(tmp_path: Path) -> None:
    """The red case, pinned. Before A3 there was NO cancel path at all — that absence is the
    defect, and this is the assertion that fails the moment it comes back.

    It also pins the O4 seam: the route is not on `test_workspace_seam_route_table.ALLOWLIST`, so
    a headerless request must 401 `workspace.header_required` rather than cancelling anything.
    """
    app = create_app(tmp_path / "engine-cache")
    routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set()) or set()
    }
    assert ("POST", "/agent/runs/{run_id}/cancel") in routes

    bare = TestClient(app)  # deliberately NO X-Workspace-Id
    refused = bare.post("/agent/runs/run_anything/cancel")
    assert refused.status_code == 401
    assert refused.json()["detail"]["code"] == "workspace.header_required"
