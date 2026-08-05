from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from langchain.agents import create_agent
from pydantic import BaseModel, ValidationError

from clue_core.entity_research import (
    AgentFramework,
    EntityAgentToolSurface,
    EntityResearchAuthorityContract,
    EntityResearchJobAuthorization,
    EntityResearchJobStatus,
    EntityResearchSelection,
    FacetDelegationContract,
    FieldResearchSourcePlan,
    GovernedResearchToolRequest,
    ParallelToolExecutionContract,
    PersistedResearchToolResult,
    ProviderOperationCausation,
    ResearchFinalizationProposal,
    ResearchFinalizationReceipt,
    ResearchRunLifecycleContract,
    ResearchSelectionBasis,
)

_FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "entity_research"

_MODELS: dict[str, type[BaseModel]] = {
    model.__name__: model
    for model in (
        EntityAgentToolSurface,
        EntityResearchAuthorityContract,
        EntityResearchJobAuthorization,
        EntityResearchJobStatus,
        EntityResearchSelection,
        FacetDelegationContract,
        FieldResearchSourcePlan,
        GovernedResearchToolRequest,
        ParallelToolExecutionContract,
        PersistedResearchToolResult,
        ProviderOperationCausation,
        ResearchFinalizationProposal,
        ResearchFinalizationReceipt,
        ResearchRunLifecycleContract,
    )
}

_EXPECTED_FORBIDDEN_CASES = frozenset(
    {
        "old-entity-deepagent",
        "agent-dispatches-provider",
        "controller-chooses-research-tools",
        "controller-dispatches-provider",
        "duplicate-contact-agent-class",
        "duplicate-contact-tool-surface",
        "gap-only-account-agent-surface",
        "provider-sdk-tool-exposed",
        "provider-sdk-flag-exposed",
        "channel-reveal-without-validation",
        "account-selection-authorizes-contact-channel",
        "account-selection-carries-contact-identity-evidence",
        "contact-selection-admits-account-field",
        "contact-selection-without-strong-identity",
        "contact-selection-without-account-association",
        "committee-selection-without-committee-proof",
        "contact-job-target-not-selected",
        "contact-job-cross-project-scope",
        "contact-job-wrong-parent-account",
        "unconfirmed-account-launch",
        "automatic-account-to-contact-successor",
        "account-run-performs-contact-research",
        "contact-run-performs-account-research",
        "duplicate-account-run-operation",
        "manufactured-deterministic-first-attempt",
        "contact-tool-request-without-parent-account",
        "follow-up-tool-request-with-partial-lineage",
        "account-tool-request-uses-contact-tool",
        "account-tool-request-uses-contact-field",
        "lossy-result-without-raw-snapshot",
        "lossy-result-omits-requested-field",
        "lossy-inline-result-omits-found-value",
        "found-result-without-evidence",
        "rejected-result-without-decision-record",
        "account-result-contains-contact-field",
        "provider-dispatch-precedes-tool-journal",
        "follow-up-provider-operation-with-partial-lineage",
        "recursive-facet-child",
        "facet-separate-budget",
        "facet-depth-exceeds-one",
        "facet-child-count-exceeds-two",
        "disabled-facet-reserves-children",
        "parallel-calls-without-engine-admission",
        "parallel-dependent-follow-up",
        "parallel-calls-share-budget-reservation",
        "parallel-overlap-without-corroboration-authority",
        "parallel-duplicate-provider-work",
        "account-parallel-batch-contains-contact-field",
        "finalization-with-pending-provider-work",
        "completed-finalization-with-unresolved-gap",
        "needs-review-without-durable-flags",
        "account-finalization-contains-contact-field",
        "finalization-accepts-stale-state",
        "finalization-skips-spend-reconciliation",
        "model-message-alone-marks-terminal",
        "waiting-job-carries-terminal-authority",
    }
)


def _read_json(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_FIXTURE_DIR / name).read_text()))


def _lookup(root: Any, path: str | list[str | int]) -> Any:
    parts: list[str | int]
    if isinstance(path, str):
        parts = [int(part) if part.isdigit() else part for part in path.split(".")]
    else:
        parts = path
    current = root
    for part in parts:
        current = current[part]
    return current


def _resolve_fixture_refs(value: Any, root: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _resolve_fixture_refs(copy.deepcopy(_lookup(root, value[1:])), root)
    if isinstance(value, dict):
        return {key: _resolve_fixture_refs(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_fixture_refs(item, root) for item in value]
    return value


def _apply_mutation(payload: Any, mutation: dict[str, Any]) -> None:
    path = mutation["path"]
    parent = _lookup(payload, path[:-1]) if path[:-1] else payload
    key = path[-1]
    operation = mutation["op"]
    if operation == "set":
        parent[key] = copy.deepcopy(mutation["value"])
    elif operation == "append":
        _lookup(payload, path).append(copy.deepcopy(mutation["value"]))
    elif operation == "remove":
        del parent[key]
    else:  # pragma: no cover - the fixture schema is closed by this assertion
        raise AssertionError(f"unknown fixture mutation: {operation}")


@pytest.fixture(scope="module")
def canonical_fixture() -> dict[str, Any]:
    return _read_json("r0_contract_fixture.json")


@pytest.fixture(scope="module")
def forbidden_fixture() -> dict[str, Any]:
    return _read_json("r0_forbidden_flows.json")


def test_exact_langchain_create_agent_constructor_is_available() -> None:
    assert callable(create_agent)
    assert create_agent.__name__ == "create_agent"
    assert AgentFramework.LANGCHAIN_CREATE_AGENT.value == "langchain.agents.create_agent"
    assert AgentFramework.DEEPAGENTS_CREATE_DEEP_AGENT.value == "deepagents.create_deep_agent"


def test_canonical_r0_contract_fixture_is_fully_valid(
    canonical_fixture: dict[str, Any],
) -> None:
    def resolve(key: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            _resolve_fixture_refs(copy.deepcopy(canonical_fixture[key]), canonical_fixture),
        )

    EntityResearchAuthorityContract.model_validate(resolve("authority"))
    account_selection = EntityResearchSelection.model_validate(resolve("account_selection"))
    contact_selection = EntityResearchSelection.model_validate(resolve("contact_selection"))
    ResearchRunLifecycleContract.model_validate(resolve("account_lifecycle"))
    ResearchRunLifecycleContract.model_validate(resolve("contact_lifecycle"))
    EntityResearchJobAuthorization.model_validate(resolve("non_committee_contact_job"))
    FieldResearchSourcePlan.model_validate(resolve("qualitative_source_plan"))
    GovernedResearchToolRequest.model_validate(resolve("tool_request"))
    PersistedResearchToolResult.model_validate(resolve("tool_result"))
    ProviderOperationCausation.model_validate(resolve("causation"))
    ProviderOperationCausation.model_validate(resolve("follow_up_causation"))
    FacetDelegationContract.model_validate(resolve("facet_policy"))
    ParallelToolExecutionContract.model_validate(resolve("parallel_execution"))
    ResearchFinalizationProposal.model_validate(resolve("finalization_proposal"))
    ResearchFinalizationReceipt.model_validate(resolve("finalization_receipt"))
    EntityResearchJobStatus.model_validate(resolve("terminal_job_status"))

    assert account_selection.channel_permissions == ()
    assert {subject.basis for subject in contact_selection.subjects} == {
        ResearchSelectionBasis.COMMITTEE_MEMBER,
        ResearchSelectionBasis.USER_SELECTED_ASSOCIATED_CONTACT,
    }


def test_forbidden_flow_fixture_is_complete_and_unique(
    forbidden_fixture: dict[str, Any],
) -> None:
    assert forbidden_fixture["contract_version"] == "m8d-r0-v1"
    case_ids = [case["case_id"] for case in forbidden_fixture["cases"]]
    assert len(case_ids) == len(set(case_ids))
    assert frozenset(case_ids) == _EXPECTED_FORBIDDEN_CASES
    assert {case["model"] for case in forbidden_fixture["cases"]} <= _MODELS.keys()


def test_public_r0_contract_schemas_match_frozen_fingerprints() -> None:
    fixture = _read_json("r0_schema_fingerprints.json")
    assert fixture["contract_version"] == "m8d-r0-v1"
    actual = {
        name: hashlib.sha256(
            json.dumps(
                model.model_json_schema(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
        ).hexdigest()
        for name, model in _MODELS.items()
        if name != "EntityAgentToolSurface"
    }
    assert actual == fixture["sha256"]


@pytest.mark.parametrize(
    "case",
    _read_json("r0_forbidden_flows.json")["cases"],
    ids=lambda case: case["case_id"],
)
def test_forbidden_old_flow_is_rejected(
    case: dict[str, Any],
    canonical_fixture: dict[str, Any],
) -> None:
    payload = _resolve_fixture_refs(
        copy.deepcopy(_lookup(canonical_fixture, case["base"])), canonical_fixture
    )
    for mutation in case["mutations"]:
        _apply_mutation(payload, mutation)

    model = _MODELS[case["model"]]
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(payload)

    assert case["expected_error"] in str(exc_info.value)
