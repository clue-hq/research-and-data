"""Provider/DB-free S5-F authority and replay-contract acceptance."""

from __future__ import annotations

import pytest
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from clue_api.agent_execution_wiring import _trusted_tool_arguments
from clue_api.agent_runtime_wiring import _with_trusted_runtime
from clue_api.product_selection_gate_tools import (
    OpenProductSelectionGateInput,
    build_product_selection_gate_tools,
)
from clue_api.turn_binding import CapturedTurn, CapturedTurnUnavailable
from clue_gateway.agent_model import provider_compatible_tool_schema
from tests.agents.conftest import constitution


def _captured_turn() -> CapturedTurn:
    return CapturedTurn(
        onboarding_input_id="11111111-1111-4111-8111-111111111111",
        artifact_key="turns/present-product.json",
        sha256="0" * 64,
        byte_count=21,
        answer="Help me choose a product",
        turn_id="22222222-2222-4222-8222-222222222222",
        user_instruction="Help me choose a product",
        source_turn_ref="turn-action:22222222-2222-4222-8222-222222222222",
    )


def test_selection_gate_model_schema_exposes_no_authority_or_candidate_fields() -> None:
    runtime_model = _with_trusted_runtime(
        OpenProductSelectionGateInput,
        name="OpenProductSelectionGateS5FRuntime",
    )

    async def probe(**_kwargs: object) -> str:  # pragma: no cover - schema only
        raise AssertionError("schema probe must not execute")

    tool = StructuredTool.from_function(
        coroutine=probe,
        name="s5f_product_selection_schema_probe",
        description="S5-F schema probe.",
        args_schema=runtime_model,
    )
    parameters = provider_compatible_tool_schema(convert_to_openai_tool(tool))["function"][
        "parameters"
    ]
    assert parameters["properties"] == {}
    assert set(runtime_model.model_fields) == {"runtime"}
    for forged in (
        {"source_turn_ref": _captured_turn().source_turn_ref},
        {"product_id": "product-forged"},
        {"client_entity_id": "33333333-3333-4333-8333-333333333333"},
        {"company_client_kb_version": 999},
        {"products": [{"product_id": "product-forged"}]},
    ):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            runtime_model.model_validate({"runtime": None, **forged})


def test_selection_gate_receives_only_the_current_captured_turn_ref() -> None:
    captured = _captured_turn()
    merged = _trusted_tool_arguments(
        arguments={},
        input_model=OpenProductSelectionGateInput,
        constitution=constitution(),
        captured_turn=captured,
    )
    assert merged == {"source_turn_ref": captured.source_turn_ref}
    assert OpenProductSelectionGateInput.model_validate(merged).source_turn_ref == (
        captured.source_turn_ref
    )

    with pytest.raises(ValueError, match="trusted turn authority"):
        _trusted_tool_arguments(
            arguments={"source_turn_ref": captured.source_turn_ref},
            input_model=OpenProductSelectionGateInput,
            constitution=constitution(),
            captured_turn=captured,
        )
    with pytest.raises(CapturedTurnUnavailable, match="captured input"):
        _trusted_tool_arguments(
            arguments={},
            input_model=OpenProductSelectionGateInput,
            constitution=constitution(),
            captured_turn=None,
        )


def test_selection_gate_is_free_domain_idempotent_and_confirms_nothing() -> None:
    (tool,) = build_product_selection_gate_tools()
    assert tool.descriptor.address == "open_product_selection_gate@1"
    assert tool.descriptor.effect_class.value == "write"
    assert tool.descriptor.replay.policy.value == "domain_idempotent"
    assert tool.descriptor.replay.external_boundary.value == "none"
    assert tool.descriptor.pin_requirements == ("project", "client_kb")
    estimate = tool.estimate(OpenProductSelectionGateInput(source_turn_ref="turn-action:present"))
    assert estimate.cost_cents == 0
