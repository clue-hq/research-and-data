"""C6.0 real async-Postgres checkpoint/crash-resume dependency spike."""

from __future__ import annotations

from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text

from clue_db import database_url, db_lifespan, transaction
from tests.db.conftest import _db_available, run_async


class ResumeState(TypedDict):
    value: int


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://",
        "postgresql://",
    )


def test_async_postgres_saver_resumes_failed_node_without_replaying_completed_node() -> None:
    """A fresh compiled graph resumes at the failed node from durable Postgres state."""

    if not _db_available():
        pytest.skip("CLUE_DATABASE_URL unset or database unreachable")

    async def run() -> None:
        calls = {"prepare": 0, "unstable": 0}

        def prepare(state: ResumeState) -> dict[str, int]:
            calls["prepare"] += 1
            return {"value": state["value"] + 1}

        def unstable(state: ResumeState) -> dict[str, int]:
            calls["unstable"] += 1
            if calls["unstable"] == 1:
                raise RuntimeError("deterministic C6 checkpoint spike")
            return {"value": state["value"] + 1}

        builder = StateGraph(ResumeState)
        builder.add_node("prepare", prepare)
        builder.add_node("unstable", unstable)
        builder.add_edge(START, "prepare")
        builder.add_edge("prepare", "unstable")
        builder.add_edge("unstable", END)
        config = {"configurable": {"thread_id": f"c6-spike-{uuid4()}"}}

        async with db_lifespan():
            try:
                async with AsyncPostgresSaver.from_conn_string(
                    _psycopg_dsn(database_url())
                ) as saver:
                    await saver.setup()
                    first_graph = builder.compile(checkpointer=saver)
                    with pytest.raises(RuntimeError, match="checkpoint spike"):
                        await first_graph.ainvoke({"value": 0}, config)

                    checkpoint = await first_graph.aget_state(config)
                    assert checkpoint.values["value"] == 1
                    assert checkpoint.next == ("unstable",)
                    assert calls == {"prepare": 1, "unstable": 1}

                    # Simulate a process restart by compiling a fresh graph against the same saver.
                    resumed_graph = builder.compile(checkpointer=saver)
                    result = await resumed_graph.ainvoke(None, config)
                    assert result == {"value": 2}
                    assert calls == {"prepare": 1, "unstable": 2}
            finally:
                # LangGraph owns these runtime tables, not Alembic.  Leave the schema pristine.
                async with transaction() as conn:
                    for table in (
                        "checkpoint_blobs",
                        "checkpoint_writes",
                        "checkpoints",
                        "checkpoint_migrations",
                    ):
                        await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))

    run_async(run())
