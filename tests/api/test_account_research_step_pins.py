"""Production account-research dynamic-pin boundary regressions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from clue_api.account_research_wiring import AccountResearchStepPinProvider
from clue_api.stage0_recipe import RecipeStep
from clue_core import new_operation_id
from clue_execution import CompatibilityContext, PinRequest, ResourceObservation
from clue_toolbelt import ToolContext
from tests.db.conftest import run_async


class _Compatibility:
    def __init__(self) -> None:
        self.observed: list[tuple[str, str]] = []

    async def observe_current(
        self,
        *,
        kind: str,
        key: str,
        context: CompatibilityContext,
    ) -> ResourceObservation:
        del context
        self.observed.append((kind, key))
        return ResourceObservation(
            version="1",
            digest=("a" * 64),
            status="active",
        )


@asynccontextmanager
async def _unused_conn() -> Any:
    yield None


def test_account_research_dynamic_pins_do_not_duplicate_static_coverage_policy() -> None:
    async def scenario() -> None:
        compatibility = _Compatibility()
        provider = AccountResearchStepPinProvider(compatibility=compatibility)  # type: ignore[arg-type]
        explicit = PinRequest(kind="source_manifest", key="exa_deep", version="1")
        pins = await provider.pins_for(
            RecipeStep(
                step_id="research",
                tool_name="research_account_gaps",
                tool_version="2",
                input_refs={
                    "project_run_id": "00000000-0000-0000-0000-000000000001",
                    "account_entity_id": "00000000-0000-0000-0000-000000000002",
                },
                pin_requests=(explicit,),
            ),
            ctx=ToolContext(
                workspace_id="ws-account-research-pins",
                actor="agent",
                conn_factory=_unused_conn,
                operation_id=new_operation_id(),
            ),
        )
        assert [pin.kind for pin in pins] == [
            "project_run",
            "account",
            "field_registry",
            "source_registry",
            "source_manifest",
        ]
        assert ("coverage_policy", "default") not in compatibility.observed

    run_async(scenario())
