"""A design run's collected model calls become agent_model_call rows on the design leg's turn."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from clue_agents import AgentTurnRequest
from clue_agents.contracts import AgentRole, ResourceKind
from clue_api.design_leg_wiring import receipts_from_design_run
from tests.agents.conftest import artifact, constitution, resource
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


@pytest.fixture
def design_turn_request() -> AgentTurnRequest:
    """One design-leg turn request, built the way ``design_leg_wiring._request`` builds it.

    Placeholder ids: ``receipts_from_design_run`` reads only the turn, execution and workspace off
    it, so nothing here needs to exist in a database.
    """
    leg_id = "leg-receipts-1"
    return AgentTurnRequest(
        turn_id=uuid4(),
        thread_id="thr-design-receipts",
        constitution=constitution(
            role=AgentRole.DESIGN,
            workspace_root_id=f"design-leg:{leg_id}",
            profile_ref=resource(ResourceKind.PROFILE, "design"),
        ),
        user_message_artifact_ref=artifact("user-message.txt"),
        requested_at=datetime.now(UTC),
    )


def _collected(sequence: int, *, status: str = "completed", role: str = "design_author") -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "run_id": str(uuid4()),
        "sequence": sequence,
        "requested_model": "x-ai/grok-4.6",
        "answering_model": "x-ai/grok-4.6" if status == "completed" else None,
        "status": status,
        "role": role,
        "input_tokens": 120,
        "output_tokens": 9,
        "cache_read_input_tokens": 40,
        "cost_cents": "0.87" if status == "completed" else None,
        "cost_source": "metered" if status == "completed" else None,
        "langfuse_trace_id": "t1",
        "langfuse_observation_id": f"o{sequence}",
        "latency_ms": 812.5,
        "error_code": None if status == "completed" else "timeout_error",
        "started_at": now,
        "completed_at": now,
    }


def test_receipts_carry_the_design_role_and_the_gateway_cost(
    design_turn_request: AgentTurnRequest,
) -> None:
    receipts = receipts_from_design_run(
        {"model_calls": [_collected(1), _collected(2, status="failed")]},
        request=design_turn_request,
    )
    assert [r.sequence for r in receipts] == [1, 2]
    assert all(r.role is AgentRole.DESIGN for r in receipts)
    assert receipts[0].cost_usd == Decimal("0.008700") and receipts[0].cost_source == "metered"
    assert receipts[0].langfuse_observation_id == "o1"
    assert receipts[1].status == "failed" and receipts[1].error_code == "timeout_error"
    assert receipts[1].cost_usd is None


def test_a_sequence_offset_lands_a_run_after_the_calls_before_it(
    design_turn_request: AgentTurnRequest,
) -> None:
    """A batch's second run numbers its calls after the first run's — the ledger keys receipts
    on ``(turn_id, sequence)`` and every run of a batch lands on ONE turn."""
    receipts = receipts_from_design_run(
        {"model_calls": [_collected(1), _collected(2)]},
        request=design_turn_request,
        sequence_offset=31,
    )
    assert [r.sequence for r in receipts] == [32, 33]
    # The default is the shipped one-run numbering, untouched.
    assert [
        r.sequence
        for r in receipts_from_design_run(
            {"model_calls": [_collected(1)]}, request=design_turn_request
        )
    ] == [1]


def test_a_run_without_model_calls_yields_no_receipts(
    design_turn_request: AgentTurnRequest,
) -> None:
    assert receipts_from_design_run({}, request=design_turn_request) == ()


# --- the re-join paths (ruling T5-1) -----------------------------------------------------------
#
# ``_dispatch`` returns a terminal design run from three places, and only one of them drives.
# A run this dispatch merely RE-JOINS — a legacy terminal row, or one a separately claimed
# worker finished before the crashed producer wrote its selection dependencies — still spent
# real money on real model calls, and this dispatch owns the only platform turn they belong to.
# These two tests drive ``_dispatch`` straight at each re-join with a lane that refuses to run.


class _RecordingJournal:
    def __init__(self) -> None:
        self.receipts: list[Any] = []

    async def record_model_call(self, *, receipt: Any) -> None:
        self.receipts.append(receipt)


class _LaneThatMustNotDrive:
    async def drive(self, *, envelope: Any) -> None:
        raise AssertionError("a re-joined terminal design run must never be re-driven")


def _conn_factory() -> Any:
    class _Held:
        async def __aenter__(self) -> str:
            return "conn"

        async def __aexit__(self, *exc: object) -> None:
            return None

    return _Held


def _terminal_run(
    *, sequence: int | None = None, sequences: tuple[int, ...] = ()
) -> dict[str, Any]:
    calls = [_collected(n) for n in ((sequence,) if sequence is not None else sequences)]
    return {
        "run_id": "run_x",
        "status": "succeeded",
        "document_id": None,
        # The design API's shipped DTO key for the ``result_json`` column.
        "result": {"status": "accepted", "model_calls": calls},
    }


def _dispatch_against(
    monkeypatch: pytest.MonkeyPatch,
    request: AgentTurnRequest,
    *,
    run: dict[str, Any] | None = None,
    config: dict[str, Any],
    runs_by_position: dict[int, dict[str, Any]] | None = None,
) -> _RecordingJournal:
    """Run the dispatch where ``get_run`` already answers terminal, and return the journal.

    A one-document batch (spec §3.3) by default: the addressed set is the leg's single
    synthesised document, so this is the same re-join branch it always was. ``runs_by_position``
    makes it a real batch — one terminal run per addressed document, keyed by the position each
    derived run id is seeded from.
    """
    from clue_api import design_leg_wiring as wiring

    turn_id = request.turn_id
    workspace_id = request.constitution.workspace_id
    if runs_by_position is None:
        assert run is not None
        runs_by_position = {0: run}
    runs_by_id = {
        wiring.design_leg_run_id(turn_id, position): terminal
        for position, terminal in runs_by_position.items()
    }
    documents = tuple(
        {"document_id": None, "position": position, "note": "", "title": None}
        for position in sorted(runs_by_position)
    )

    def _job_for(run_id: str) -> dict[str, Any]:
        return {
            "workspace_id": workspace_id,
            "payload": {
                "kind": "agent_turn",
                "work_id": str(wiring.design_runs.work_id_for_run(run_id)),
                "workspace_id": workspace_id,
                "run_id": run_id,
                "checkpoint_thread_id": run_id,
                "config": config,
            },
        }

    class _Runs:
        work_id_for_run = staticmethod(wiring.design_runs.work_id_for_run)

        @staticmethod
        async def get_run(conn: Any, *, workspace_id: str, run_id: str) -> dict[str, Any]:
            return runs_by_id[run_id]

        @staticmethod
        async def get_run_by_work_id(conn: Any, *, work_id: Any) -> dict[str, Any]:
            (run_id,) = [
                candidate
                for candidate in runs_by_id
                if wiring.design_runs.work_id_for_run(candidate) == work_id
            ]
            return _job_for(run_id)

    monkeypatch.setattr(wiring, "design_runs", _Runs)
    # Only reachable on the design-memory path; ``None`` keeps the DB-backed receipt store out.
    monkeypatch.setattr(wiring, "selection_dependency_receipt", lambda *a, **k: None)

    journal = _RecordingJournal()
    runner = wiring.DesignLegTurnRunner(
        profiles=None,
        artifacts=None,
        turns=journal,
        history=None,
        lane=_LaneThatMustNotDrive(),
        conn_factory=_conn_factory(),
    )
    asyncio.run(
        runner._dispatch_batch(
            submission=SimpleNamespace(
                turn_id=turn_id,
                thread_id=request.thread_id,
                project_id=request.constitution.project_id,
            ),
            leg={"id": "leg-receipts-1", "state": "running", "document_id": None},
            leg_id="leg-receipts-1",
            execution_id=request.constitution.execution_id,
            user_message_ref=request.user_message_artifact_ref,
            prior_history=(),
            documents=documents,
            document_rows={},
            account_cards={},
            leg_document_count=len(documents),
            focus_refs=(),
            workspace_id=workspace_id,
            scope_pin=None,
            turn_request=request,
        )
    )
    return journal


def test_a_legacy_terminal_re_join_still_records_its_receipts(
    monkeypatch: pytest.MonkeyPatch, design_turn_request: AgentTurnRequest
) -> None:
    journal = _dispatch_against(
        monkeypatch, design_turn_request, run=_terminal_run(sequence=3), config={}
    )
    assert [r.sequence for r in journal.receipts] == [3]
    assert journal.receipts[0].role is AgentRole.DESIGN


def test_a_crashed_producer_re_join_still_records_its_receipts(
    monkeypatch: pytest.MonkeyPatch, design_turn_request: AgentTurnRequest
) -> None:
    journal = _dispatch_against(
        monkeypatch,
        design_turn_request,
        run=_terminal_run(sequence=4),
        # A design_memory key sends the dispatch past the legacy re-join to the second one.
        config={"design_memory": {"selected": []}},
    )
    assert [r.sequence for r in journal.receipts] == [4]
    assert journal.receipts[0].cost_usd == Decimal("0.008700")


def test_a_batch_records_every_run_on_the_one_turn_numbered_after_the_runs_before_it(
    monkeypatch: pytest.MonkeyPatch, design_turn_request: AgentTurnRequest
) -> None:
    """Three terminal re-joins on one turn: each run numbers its calls from 1, and the ledger
    keys ``(turn_id, sequence)`` — the first live batch (2026-09-20) recorded run 0's 1..31 and
    crashed on run 1's call 1. Position order, cumulative offsets, gapless."""
    journal = _dispatch_against(
        monkeypatch,
        design_turn_request,
        config={},
        runs_by_position={
            0: _terminal_run(sequences=(1, 2)),
            1: _terminal_run(sequences=(1, 2, 3)),
            2: _terminal_run(sequences=(1,)),
        },
    )
    assert [r.sequence for r in journal.receipts] == [1, 2, 3, 4, 5, 6]
    assert len({r.model_call_id for r in journal.receipts}) == 6
    assert all(r.turn_id == design_turn_request.turn_id for r in journal.receipts)


def test_a_batch_run_with_no_calls_leaves_the_numbering_where_it_was(
    monkeypatch: pytest.MonkeyPatch, design_turn_request: AgentTurnRequest
) -> None:
    journal = _dispatch_against(
        monkeypatch,
        design_turn_request,
        config={},
        runs_by_position={
            0: _terminal_run(sequences=(1, 2)),
            1: _terminal_run(sequences=()),
            2: _terminal_run(sequences=(1,)),
        },
    )
    assert [r.sequence for r in journal.receipts] == [1, 2, 3]
