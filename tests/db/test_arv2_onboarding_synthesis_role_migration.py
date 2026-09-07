"""The onboarding_synthesis agent role is admitted by every role CHECK (O4 Task 1)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_agents.contracts import AgentRole
from clue_db import db_lifespan

from .conftest import run_async


def test_the_role_enum_has_onboarding_synthesis() -> None:
    assert AgentRole.ONBOARDING_SYNTHESIS.value == "onboarding_synthesis"


@pytest.mark.usefixtures("require_db")
def test_every_role_check_admits_onboarding_synthesis() -> None:
    async def scenario() -> dict[str, str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                    "WHERE conname IN "
                    "('agent_turn_role', 'agent_plan_role', 'agent_delegation_roles', "
                    "'agent_model_call_role')"
                )
            )
            return {str(r.conname): str(r.definition) for r in rows}

    checks = run_async(scenario())
    assert set(checks) == {
        "agent_turn_role",
        "agent_plan_role",
        "agent_delegation_roles",
        # Added by dfb9fa040b13: the model-call ledger is the fourth role vocabulary, and a
        # governed turn stamps it on every model round.
        "agent_model_call_role",
    }
    for definition in checks.values():
        assert "'onboarding_synthesis'" in definition
        assert "'design'" in definition  # nothing dropped
