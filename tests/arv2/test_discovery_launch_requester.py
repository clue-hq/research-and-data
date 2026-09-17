"""Who a discovery run is requested by (ruling 10′, 2026-09-11): a human invoker is the requester;
a fleet-driven launch resolves the launching turn's human from the turn's submission row, and
falls back to the invoker's id when the ref does not resolve."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from clue_api.arv2.discovery_launch import Arv2DiscoveryRequest, _requesting_human


class _Conn:
    """Answers the submitter query for one known turn and nothing for any other."""

    def __init__(self, known: dict[str, str]) -> None:
        self.known = known
        self.queries: list[dict[str, Any]] = []

    async def execute(self, statement: Any, parameters: dict[str, Any]) -> Any:
        del statement
        self.queries.append(parameters)
        submitter = self.known.get(str(parameters["turn_id"]))
        return _Result(submitter)


class _Result:
    def __init__(self, submitter: str | None) -> None:
        self._submitter = submitter

    def first(self) -> tuple[str] | None:
        return None if self._submitter is None else (self._submitter,)


def _request(**overrides: Any) -> Arv2DiscoveryRequest:
    payload: dict[str, Any] = {
        "workspace_id": "ws-1",
        "project_id": "prj-1",
        "requested_by_user_id": "svc_execution_worker",
    }
    payload.update(overrides)
    return Arv2DiscoveryRequest(**payload)


def test_a_fleet_driven_launch_names_the_turns_human() -> None:
    turn_id = uuid4()
    conn = _Conn({str(turn_id): "usr_founder"})
    request = _request(launching_turn_ref=f"turn-action:{turn_id}")
    assert asyncio.run(_requesting_human(conn, request)) == "usr_founder"  # type: ignore[arg-type]
    assert conn.queries == [{"turn_id": turn_id, "workspace_id": "ws-1"}]


def test_a_human_invoker_is_the_requester_and_no_turn_is_read() -> None:
    conn = _Conn({})
    request = _request(requested_by_user_id="usr_human")
    assert asyncio.run(_requesting_human(conn, request)) == "usr_human"  # type: ignore[arg-type]
    assert conn.queries == []


def test_an_unresolvable_or_unknown_ref_leaves_the_invokers_id_standing() -> None:
    conn = _Conn({})
    for ref in ("not-a-ref", "turn-action:not-a-uuid", f"turn-action:{uuid4()}"):
        request = _request(launching_turn_ref=ref)
        assert (
            asyncio.run(_requesting_human(conn, request))  # type: ignore[arg-type]
            == "svc_execution_worker"
        )
