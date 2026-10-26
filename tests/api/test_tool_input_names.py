"""Tool inputs must survive the agent's plan validator (CRM trial 1, finding F4).

An agent's tool call becomes a one-node plan whose bindings are keyed by the tool's input field
names, and ``clue_execution.graph.validate_graph`` refuses any key named like raw content
(``_RAW_BODY_KEYS``: ``body``, ``content``, ``text``…) — even when the field is empty. A tool with
such an input can never run from an agent turn, and only a real turn used to notice:
``write_brand_document@1`` shipped with a ``body`` field and every call was refused. These tests
catch it at build time.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from clue_agents import AgentPlan, AgentRole, ToolPin
from clue_agents.contracts import PlanToolStep
from clue_api.agent_execution_wiring import _plan_graph_and_parameters
from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import ExecutionId
from clue_execution import InteractionSlotView
from clue_execution.graph import _RAW_BODY_KEYS, validate_graph
from tests.agents.conftest import NOW, artifact

#: Registered, but granted to no agent since ``head-of-abm@v55``, and its input schema is pinned by
#: the profiles that did grant it, so renaming the field would break their replay. It stays the one
#: known exception; nothing may join it.
_UNGRANTED_LEGACY = {"write_project_document@1"}


def test_no_tool_input_is_named_like_raw_content() -> None:
    offenders = {
        descriptor.address: sorted(
            name
            for name in descriptor.input_model.model_json_schema().get("properties", {})
            if name.lower() in _RAW_BODY_KEYS
        )
        for descriptor in build_toolbelt(storage=None, gateway=None).descriptors()
    }
    offenders = {address: names for address, names in offenders.items() if names}
    assert set(offenders) == _UNGRANTED_LEGACY, (
        f"rename these tool inputs (the agent's plan validator refuses them): {offenders}"
    )


def _raw_body_issues(tool_name: str, arguments: dict[str, Any]) -> list[str]:
    tools = build_toolbelt(storage=None, gateway=None)
    descriptor = tools.descriptor(tool_name)
    pin = ToolPin(
        name=descriptor.name,
        version=descriptor.version,
        input_schema_sha256=descriptor.input_schema_sha256,
        output_schema_sha256=descriptor.output_schema_sha256,
    )
    execution_id = ExecutionId(UUID("00000000-0000-0000-0000-0000000f4f40"))
    plan = AgentPlan(
        plan_id=UUID("00000000-0000-0000-0000-0000000f4f41"),
        execution_id=execution_id,
        role=AgentRole.HEAD_OF_ABM,
        goal_ref=artifact("goal.json"),
        steps=(
            PlanToolStep(
                node_key="write",
                tool=pin,
                arguments=arguments,
                purpose="Publish a brand document.",
            ),
        ),
        proposed_at=NOW,
    )
    slot = InteractionSlotView(
        execution_id=execution_id,
        workspace_id="ws-f4",
        slot_key="stage0_interactions",
        tool_allowlist=(descriptor.address,),
        dynamic_pin_kinds=("project",),
        requirements=(),
        max_children=8,
        child_count=0,
        max_nodes=16,
        node_count=0,
    )
    graph, _parameters, parameter_schema = _plan_graph_and_parameters(
        plan=plan, tools=tools, slot=slot, arguments={"write": arguments}
    )
    review = validate_graph(
        graph,
        parameter_schema=parameter_schema,
        tool_catalog=tools,
        max_nodes=16,
        max_depth=8,
        max_fanout=8,
    )
    return [issue.location for issue in review.issues if issue.code == "raw_body_key"]


def test_write_brand_document_plans_pass_the_raw_content_check() -> None:
    turn = "turn-action:00000000-0000-0000-0000-0000000f4f42"
    inline = {"path": "company/sales-motion.md", "kind": "sales-motion", "markdown": "# Sales\n"}
    from_file = {"path": "proof/customers.md", "from_file": "outputs/customers.md"}
    for arguments in (inline, from_file):
        assert (
            _raw_body_issues("write_brand_document", {**arguments, "source_turn_ref": turn}) == []
        )


def test_the_check_still_catches_a_body_input() -> None:
    """The control: the legacy tool's ``body`` input is refused exactly as F4 was."""
    issues = _raw_body_issues(
        "write_project_document",
        {
            "document": "plan",
            "body": "# Plan\n",
            "source_turn_ref": "turn-action:00000000-0000-0000-0000-0000000f4f43",
        },
    )
    assert issues == ["$.nodes[0].bindings.body"]
