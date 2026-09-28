"""``configure_project_targeting@1`` gets its ``project`` pin from the presenting turn.

The tool carries only the trusted ``source_turn_ref`` (never a model-authored project), exactly like
the product-set gate it replaced, so its ``project`` pin must be derived from that turn. Without it
every production plan that calls the tool fails validation with "requires pin kind 'project'" and
discovery can never launch (found live 2026-09-29).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest

from clue_api import turn_action
from clue_api.project_targeting_tools import ConfigureProjectTargetingTool
from clue_api.stage0_recipe import RecipeStep, Stage0StepPinProvider
from clue_api.turn_action import TurnIdentity, derive_turn_action_ref
from clue_core import new_operation_id
from clue_execution import CompatibilityContext, ResourceObservation
from clue_toolbelt import ToolContext, ToolRegistry
from tests.db.conftest import run_async

WORKSPACE = "ws-targeting-pins"
PROJECT = "prj_targeting_pins"


class _Compatibility:
    async def observe_current(
        self, *, kind: str, key: str, context: CompatibilityContext
    ) -> ResourceObservation:
        del kind, key, context
        return ResourceObservation(version="1", digest="a" * 64, status="active")


@asynccontextmanager
async def _unused_conn() -> Any:
    yield None


def test_configure_project_targeting_pins_the_presenting_turns_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn_id = uuid4()

    async def fake_load_turn_identity(conn: Any, *, workspace_id: str, turn_id: Any) -> Any:
        del conn
        return TurnIdentity(
            turn_id=turn_id,
            workspace_id=workspace_id,
            project_id=PROJECT,
            thread_id="thr_targeting_pins",
            submitted_by_user_id="usr_targeting_pins",
            submitted_via_membership_id=None,
        )

    monkeypatch.setattr(turn_action, "load_turn_identity", fake_load_turn_identity)

    async def scenario() -> None:
        registry = ToolRegistry()
        registry.register(ConfigureProjectTargetingTool(), make_default=True)
        provider = Stage0StepPinProvider(
            compatibility=_Compatibility(),  # type: ignore[arg-type]
            conn_factory=_unused_conn,
            tools=registry,
        )
        pins = await provider.pins_for(
            RecipeStep(
                step_id="target",
                tool_name="configure_project_targeting",
                tool_version="1",
                input_refs={
                    "icp_key": "us-gi-groups",
                    "source_turn_ref": derive_turn_action_ref(turn_id),
                },
            ),
            ctx=ToolContext(
                workspace_id=WORKSPACE,
                actor="agent",
                conn_factory=_unused_conn,
                operation_id=new_operation_id(),
            ),
        )
        project_pins = [pin for pin in pins if pin.kind == "project"]
        assert [(pin.key, pin.required) for pin in project_pins] == [(PROJECT, True)]

    run_async(scenario())
