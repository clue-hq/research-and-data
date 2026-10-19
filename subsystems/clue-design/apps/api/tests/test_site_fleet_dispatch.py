"""Fleet dispatch of a site turn (Lane B Task 12): an explicit map, the capability, the trace."""

from __future__ import annotations

import pytest

from lumen_api import fleet_handler
from lumen_api.fleet_handler import DesignJobWorkHandler, DesignTurnJobError, executor_for_kind


def test_each_turn_kind_has_its_own_executor_and_an_unknown_kind_is_refused() -> None:
    from lumen_api.main import execute_agent_turn_job, execute_site_turn_job, execute_web_turn_job

    assert executor_for_kind("agent_turn") is execute_agent_turn_job
    assert executor_for_kind("web_turn") is execute_web_turn_job
    assert executor_for_kind("site_turn") is execute_site_turn_job
    with pytest.raises(DesignTurnJobError):
        executor_for_kind("poster_turn")  # never the web executor by default


def test_the_turn_pool_serves_site_turns_and_the_ingestion_pool_does_not() -> None:
    assert "site_turn" in DesignJobWorkHandler().task_capabilities[0].supported
    assert "site_turn" not in DesignJobWorkHandler(ingestion_only=True).task_capabilities[0].supported


def test_a_site_turn_is_one_named_trace_grouped_by_its_document() -> None:
    name, as_type, keys, session_key, tags = fleet_handler._TRACE_SHAPES["site_turn"]
    assert (name, as_type, session_key) == ("design.turn", "agent", "document_id")
    assert "run_id" in keys and "document_id" in keys and tags == ("kind",)
