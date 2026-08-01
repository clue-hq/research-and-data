"""Prevention gate: a silently enforced Stage-0 precondition is a failing build.

Every rule the Stage-0 tools enforce at runtime — the interview verifier's exact-quote
entailment, the per-route required fields, the captured-answer sha equality, the confirmed-run
lineage — must be stated in the field description the model reads *while filling that field*.
The assertions run against the actual model-facing schema (post ``_with_trusted_runtime`` and the
provider transform), so trusted authority fields the model never supplies are exempt by
construction, and a description that never reaches the provider cannot satisfy the gate.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from clue_api.agent_registry_wiring import C6_AGENT_TOOL_AUTHORITY
from clue_api.agent_runtime_wiring import _with_trusted_runtime
from clue_api.stage0_tools import (
    EvaluateStage0ReadinessTool,
    RecordInterviewAnswerTool,
    StartConfirmedProjectRunTool,
    StartReconTool,
    SubmitOnboardingInputTool,
    _Stage0Tool,
)
from clue_gateway.agent_model import provider_compatible_tool_schema

# The model-invocable Stage-0 surface. ``confirm_project_product`` and
# ``override_stage0_readiness`` are human-only (no role holds authority), which
# ``test_guidance_covers_every_model_invocable_stage0_tool`` re-derives rather than trusts.
_TOOLS: dict[str, type[_Stage0Tool]] = {
    "submit_onboarding_input": SubmitOnboardingInputTool,
    "start_recon": StartReconTool,
    "record_interview_answer": RecordInterviewAnswerTool,
    "evaluate_stage0_readiness": EvaluateStage0ReadinessTool,
    "start_confirmed_project_run": StartConfirmedProjectRunTool,
}

# enforced constraint -> (tool, field path, substrings the description must carry).
# Each entry names the code that refuses the call when the rule is broken.
_REQUIRED_GUIDANCE: dict[tuple[str, tuple[str, ...]], tuple[str, ...]] = {
    # stage0_tools.SubmitOnboardingInputTool.preconditions: artifact must exist here.
    ("submit_onboarding_input", ("artifact_key",)): ("captured", "workspace"),
    # governed.submit_onboarding_input immutability + the record_interview_answer sha check.
    ("submit_onboarding_input", ("content_sha256",)): ("sha-256", "exact"),
    # stage0_tools.StartReconTool.preconditions: non-empty, resolvable, same-workspace refs.
    ("start_recon", ("onboarding_input_ids",)): ("at least one", "workspace"),
    # `answer`, `onboarding_input_id` and `artifact_key` are engine-injected turn authority
    # (PC-C8 §6a, clue_api.turn_binding): the model never fills them, so under this gate's own
    # rule — state a constraint where the model authors the field — they have nothing to state
    # here. Their absence is guarded by test_c8_slice0_evidence.py::
    # test_record_interview_answer_no_longer_lets_the_model_author_the_answer_or_trusted_ids, and
    # the sha equality they used to carry is enforced before injection, engine-side.
    #
    # `brand_id` and `client_entity_id` left the model surface the same way in PC-C8 task 1.3, on
    # every Stage-0 input that declares them — they joined `project_id` in
    # MODEL_FORBIDDEN_AUTHORITY_KEYS and are served from the AgentConstitution. Same exemption,
    # same reason: this gate only binds fields the model actually fills. Two consequences, both
    # now closed by task 1.4's coordinated bump (skill v7 / profile v9):
    #   * their descriptions were dead text — accurate, unread, and part of the pinned
    #     `input_schema_sha256`, which is why 1.3 deliberately left them. 1.4 rewrote all eight
    #     (`brand_id` on submit_onboarding_input/start_recon/record_interview_answer/
    #     evaluate_stage0_readiness; `client_entity_id` on submit_onboarding_input/
    #     record_interview_answer/evaluate_stage0_readiness/start_confirmed_project_run) to the
    #     "supplied by the platform, never by you" phrasing `project_id` always used. The three
    #     `client_entity_id` declarations with no description at all (confirm_icp,
    #     import_accounts, synthesize_icps) stay bare — nothing to reword, and adding text would
    #     move their pinned digests for no model-visible gain.
    #   * the *client entity id itself* no longer has to reach the model at all. Task 1.3's layer 1
    #     put it on the project card (`project.client_entity_id`); 1.4's layer 2 removed the need
    #     — an `account` claim with no `entity_id` is engine-defaulted to the trusted client entity
    #     (`interview.resolve_claim_entity`), so the card field is now belt-and-braces rather than
    #     the model's only channel. The `entity_id` row below states the surviving rule: fill it
    #     only to name a *different*, existing entity.
    # skills/stage0-interview: route every substantive turn, unmapped included.
    ("record_interview_answer", ("statements",)): ("unmapped",),
    # interview._exact_quote: offsets index into the platform-loaded captured message.
    ("record_interview_answer", ("statements", "quote_start")): (
        "offset",
        "captured user message",
    ),
    ("record_interview_answer", ("statements", "quote_end")): (
        "offset",
        "captured user message",
    ),
    # interview._exact_quote: a claim value must be textually entailed by the exact quote.
    ("record_interview_answer", ("statements", "value")): (
        "verbatim",
        "quote_start",
        "claim",
    ),
    # interview.InterviewStatement._route_shape: per-route required fields.
    ("record_interview_answer", ("statements", "route")): ("unmapped",),
    # interview.resolve_claim_entity (PC-C8 §8, B1 layer 2): the engine defaults an `account`
    # claim's entity to the trusted client entity, and refuses a supplied id that resolves to
    # nothing (`interview_entity_not_found`) instead of silently writing it at a lower tier. Both
    # halves are stated where the model decides whether to fill the field at all.
    ("record_interview_answer", ("statements", "entity_id")): (
        "claim",
        "leave it out",
        "already exist",
        "refused",
        "contact",
    ),
    ("record_interview_answer", ("statements", "entity_type")): ("claim",),
    ("record_interview_answer", ("statements", "field_key")): ("claim", "registered"),
    ("record_interview_answer", ("statements", "memory_type")): ("memory",),
    ("record_interview_answer", ("statements", "memory_scope_type")): ("memory",),
    ("record_interview_answer", ("statements", "route_ref")): ("proposal",),
    ("record_interview_answer", ("statements", "identity_binding")): ("contact",),
    ("record_interview_answer", ("statements", "use_class")): ("contact",),
    # interview._write_claim: a correction must match workspace, entity, and field.
    ("record_interview_answer", ("statements", "correction_of_claim_id")): ("field",),
    # governed.evaluate_readiness: the deterministic floor reads exactly these metric keys.
    ("evaluate_stage0_readiness", ("metrics",)): (
        "coverage_ratio",
        "verified_claims",
        "open_policy_blocks",
        "available_field_keys",
    ),
    ("evaluate_stage0_readiness", ("agent_sufficiency_status",)): ("advisory", "never"),
    # stage0_tools.start_confirmed_project_run: exact lineage + ready-or-overridden decision.
    ("start_confirmed_project_run", ("readiness_decision_id",)): (
        "discovery_spend",
        "override",
    ),
    ("start_confirmed_project_run", ("icp_key",)): ("lineage",),
    ("start_confirmed_project_run", ("icp_version",)): ("lineage",),
    ("start_confirmed_project_run", ("client_kb_version",)): ("lineage",),
    ("start_confirmed_project_run", ("product_context_version_id",)): ("lineage",),
}


def _model_facing_parameters(tool_type: type[_Stage0Tool]) -> dict[str, Any]:
    """Reproduce the schema binding in ``agent_runtime_wiring`` exactly."""

    args_schema = _with_trusted_runtime(
        tool_type.input_model,
        name=f"{tool_type.input_model.__name__}AgentRuntime",
    )

    async def invoke(**kwargs: Any) -> str:  # pragma: no cover - never called
        raise AssertionError("schema probe")

    tool = StructuredTool.from_function(
        coroutine=invoke,
        name=tool_type.name,
        description=f"probe {tool_type.name}",
        args_schema=args_schema,
    )
    schema = provider_compatible_tool_schema(convert_to_openai_tool(tool))
    parameters = schema["function"]["parameters"]
    assert isinstance(parameters, dict)
    return parameters


def _field(parameters: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    node = parameters
    for index, name in enumerate(path):
        properties = node.get("properties", {})
        assert name in properties, f"{path} is absent from the model-facing schema"
        node = properties[name]
        if index + 1 < len(path) and "items" in node:
            node = node["items"]
    return node


def _described_fields(
    node: dict[str, Any], prefix: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    for name, child in node.get("properties", {}).items():
        path = (*prefix, name)
        yield path, child
        nested = child.get("items", child)
        if isinstance(nested, dict) and "properties" in nested:
            yield from _described_fields(nested, path)


def test_every_enforced_stage0_constraint_is_stated_where_the_model_authors_it() -> None:
    schemas = {name: _model_facing_parameters(tool) for name, tool in _TOOLS.items()}
    missing: list[str] = []
    for (tool_name, path), substrings in _REQUIRED_GUIDANCE.items():
        description = _field(schemas[tool_name], path).get("description", "").casefold()
        missing.extend(
            f"{tool_name}.{'.'.join(path)} must state {substring!r}"
            for substring in substrings
            if substring.casefold() not in description
        )
    assert missing == []


def test_every_model_visible_stage0_field_carries_guidance() -> None:
    undocumented: list[str] = []
    for name, tool in _TOOLS.items():
        for path, node in _described_fields(_model_facing_parameters(tool)):
            if len(node.get("description", "").strip()) < 20:
                undocumented.append(f"{name}.{'.'.join(path)}")
    assert undocumented == []


def test_guidance_covers_every_model_invocable_stage0_tool() -> None:
    invocable = {
        subclass.name
        for subclass in _Stage0Tool.__subclasses__()
        if C6_AGENT_TOOL_AUTHORITY.get(subclass.name)
    }
    assert invocable == set(_TOOLS)
    assert {tool for tool, _ in _REQUIRED_GUIDANCE} <= set(_TOOLS)
