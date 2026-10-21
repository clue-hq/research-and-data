"""Stream tokens for a chat thread's live stream (CRM trial 1, F2; R-10.1).

The thread stream's single-use token names its subject as ``('agent_thread', <thread id>)``, so
the subject vocabulary CHECK learns the new kind. The downgrade deletes those tokens before it
restores the narrower CHECK — they are short-lived and single-use, so nothing is lost.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clue_db import db_lifespan

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PREVIOUS_REVISION = "3b800d603402"
_WS = "ws-agent-thread-token"


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


async def _insert_thread_token() -> None:
    async with db_lifespan() as engine, engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO workspace (workspace_id, name) VALUES (:ws, 'Thread tokens') "
                "ON CONFLICT DO NOTHING"
            ),
            {"ws": _WS},
        )
        await conn.execute(
            text(
                "INSERT INTO stream_token (workspace_id, subject_kind, subject_id, expires_at) "
                "VALUES (:ws, 'agent_thread', 'thr_migration', now() + interval '5 minutes')"
            ),
            {"ws": _WS},
        )


async def _clear() -> None:
    async with db_lifespan() as engine, engine.begin() as conn:
        await conn.execute(text("DELETE FROM stream_token WHERE workspace_id = :ws"), {"ws": _WS})


async def _thread_tokens() -> int:
    async with db_lifespan() as engine, engine.connect() as conn:
        return int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM stream_token "
                        "WHERE workspace_id = :ws AND subject_kind = 'agent_thread'"
                    ),
                    {"ws": _WS},
                )
            ).scalar_one()
        )


@pytest.mark.usefixtures("require_db")
def test_agent_thread_tokens_are_allowed_and_the_downgrade_removes_them() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    run_async(_clear())
    run_async(_insert_thread_token())
    assert run_async(_thread_tokens()) == 1

    command.downgrade(cfg, _PREVIOUS_REVISION)
    assert run_async(_thread_tokens()) == 0
    with pytest.raises(IntegrityError):
        run_async(_insert_thread_token())

    command.upgrade(cfg, "head")
    run_async(_insert_thread_token())
    assert run_async(_thread_tokens()) == 1
    run_async(_clear())
