"""Lane 3 slice 4, Task 3: a turn's read tools tag the turn's trace with the entity they served."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from clue_api.arv2.read_tools import (
    AccountResearch,
    Arv2ReadRefused,
    ClaimsQueryPage,
    ReadAccountResearchTool,
    ReadClaimsTool,
)
from clue_core import new_operation_id
from clue_obs.langfuse import ENTITIES_METADATA_KEY, observation, propagate_trace
from clue_toolbelt import PreconditionFailed, ToolContext
from tests._langfuse import finished_spans, langfuse_installed
from tests.db.conftest import run_async


class _Service:
    def __init__(self, *, refuse: bool = False) -> None:
        self._refuse = refuse

    async def read_account_research(self, **kwargs: Any) -> AccountResearch:
        if self._refuse:
            raise Arv2ReadRefused("account_not_found", "not yours")
        return AccountResearch(
            account_entity_id=kwargs["account_entity_id"],
            account_name="Acme",
            section="claims",
            overview=(),
            claims=(),
            truncated=False,
            excluded={},
            offset=0,
            next_offset=None,
            prefixes={},
        )

    async def read_claims(self, **kwargs: Any) -> ClaimsQueryPage:
        if self._refuse:
            raise Arv2ReadRefused("entity_not_found", "not yours")
        return ClaimsQueryPage(
            entity_id=kwargs["entity_id"],
            entity_type="contact",
            claims=(),
            excluded={},
            prefixes={},
            offset=0,
            next_offset=None,
            truncated=False,
        )


class _NullConnFactory:
    def __call__(self) -> Any:
        raise AssertionError("the fake service opens no connection")


def _ctx() -> ToolContext:
    return ToolContext(
        workspace_id="ws-1",
        actor="agent",
        conn_factory=_NullConnFactory(),  # type: ignore[arg-type]
        operation_id=new_operation_id(),
    )


@contextmanager
def _turn() -> Iterator[None]:
    """The turn shape in production: a trace opened with ``propagate_trace`` under a live span.

    The ``propagate_trace`` entry seeds the entity accumulator in THIS context, so each tool
    call's ``asyncio.run`` copies the same set and mutates it in place — which is what makes a
    turn's successive reads accumulate rather than overwrite.
    """

    with observation("turn", as_type="agent"), propagate_trace(trace_name="head-of-abm.turn"):
        yield


def _tagged(spans: Any) -> list[str]:
    return [
        dict(s.attributes or {})[f"langfuse.trace.metadata.{ENTITIES_METADATA_KEY}"]
        for s in spans
        if s.name == "entities.tagged"
    ]


def test_off_the_tools_answer_as_before() -> None:
    result = run_async(
        ReadClaimsTool(_Service()).invoke(  # type: ignore[arg-type]
            ReadClaimsTool.input_model(entity_id="con-1"), _ctx()
        )
    )
    assert result.references["entity_id"] == "con-1"


def test_read_claims_tags_the_entity_it_served() -> None:
    with langfuse_installed() as (exporter, _provider):
        with _turn():
            run_async(
                ReadClaimsTool(_Service()).invoke(  # type: ignore[arg-type]
                    ReadClaimsTool.input_model(entity_id="con-1"), _ctx()
                )
            )
        spans = finished_spans(exporter)
    assert _tagged(spans) == ["con-1"]


def test_read_account_research_tags_the_account_and_a_turn_accumulates() -> None:
    with langfuse_installed() as (exporter, _provider):
        with _turn():
            run_async(
                ReadAccountResearchTool(_Service()).invoke(  # type: ignore[arg-type]
                    ReadAccountResearchTool.input_model(
                        account_entity_id="acc-1", section="claims"
                    ),
                    _ctx(),
                )
            )
            run_async(
                ReadClaimsTool(_Service()).invoke(  # type: ignore[arg-type]
                    ReadClaimsTool.input_model(entity_id="con-1"), _ctx()
                )
            )
        spans = finished_spans(exporter)
    assert _tagged(spans) == ["acc-1", "acc-1,con-1"]


def test_a_refused_read_tags_nothing() -> None:
    with langfuse_installed() as (exporter, _provider):
        with _turn(), pytest.raises(PreconditionFailed):
            run_async(
                ReadClaimsTool(_Service(refuse=True)).invoke(  # type: ignore[arg-type]
                    ReadClaimsTool.input_model(entity_id="con-1"), _ctx()
                )
            )
        spans = finished_spans(exporter)
    assert _tagged(spans) == []
