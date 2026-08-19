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
        "contact-selection-authorizes-committee-source",
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
    # The receipt was added compatibly: pre-receipt selections remain exact historical replay
    # inputs, while every new Account launch pins one in the launcher transaction.
    assert account_selection.discovery_receipt is None
    assert contact_selection.discovery_receipt is None
    assert {subject.basis for subject in contact_selection.subjects} == {
        ResearchSelectionBasis.COMMITTEE_MEMBER,
        ResearchSelectionBasis.USER_SELECTED_ASSOCIATED_CONTACT,
    }


def test_account_profile_run_can_exclude_committee_discovery(
    canonical_fixture: dict[str, Any],
) -> None:
    payload = cast(
        dict[str, Any],
        _resolve_fixture_refs(
            copy.deepcopy(canonical_fixture["account_lifecycle"]), canonical_fixture
        ),
    )
    selection = payload["selection"]
    selection["committee_source_keys"] = []
    selection["admitted_source_keys"] = [
        source for source in selection["admitted_source_keys"] if source != "sumble_people"
    ]
    payload["operations"] = ["account_profile"]

    lifecycle = ResearchRunLifecycleContract.model_validate(payload)

    assert tuple(item.value for item in lifecycle.operations) == ("account_profile",)
    assert lifecycle.selection.committee_source_keys == ()


def test_an_admitted_field_may_carry_no_authorized_source_at_all(
    canonical_fixture: dict[str, Any],
) -> None:
    """A field no source can *request* is admitted with an empty authority, not omitted.

    Settlement F3: source ownership and wire-requestability are different facts, so a launcher can
    legitimately compile a profile row whose every owning source structurally cannot ask for it.
    Representing that as an empty authority keeps the field on the coverage axis (it settles as an
    honest gap) while authorizing exactly nothing — the engine refuses any request naming it, and
    the run-wide admitted sources gain nothing on its behalf. Dropping the field instead would
    make the row vanish; inventing a source for it would authorize an impossible dispatch.
    """

    payload = cast(
        dict[str, Any],
        _resolve_fixture_refs(
            copy.deepcopy(canonical_fixture["account_selection"]), canonical_fixture
        ),
    )
    unbuyable = payload["field_source_authority"][0]["field_key"]
    payload["field_source_authority"][0]["source_keys"] = []
    payload["admitted_source_keys"] = sorted(
        {source for item in payload["field_source_authority"] for source in item["source_keys"]}
        | set(payload["committee_source_keys"])
    )

    selection = EntityResearchSelection.model_validate(payload)

    authority = {item.field_key: item.source_keys for item in selection.field_source_authority}
    assert authority[unbuyable] == ()
    assert unbuyable in selection.admitted_field_keys


def test_account_result_can_losslessly_project_multiple_grounded_committee_contacts(
    canonical_fixture: dict[str, Any],
) -> None:
    payload = copy.deepcopy(canonical_fixture["tool_result"])
    account_id = payload["target_entity_id"]

    def discovered(contact_id: str, title: str) -> dict[str, Any]:
        return {
            "subject_type": "contact",
            "target_entity_id": contact_id,
            "parent_account_id": account_id,
            "strong_identity_claim_refs": [f"claim:identity:{contact_id}"],
            "association_evidence_refs": [f"claim:employment:{contact_id}"],
            "fields": [
                {
                    "field_key": "contact.profile.title",
                    "outcome": "found",
                    "value": title,
                    "value_ref": f"artifact:value:{contact_id}",
                    "claim_delta": "accepted",
                    "claim_refs": [f"claim:title:{contact_id}"],
                    "decision_refs": [],
                    "evidence": [
                        {
                            "evidence_ref": f"evidence:title:{contact_id}",
                            "source_key": "sumble_people",
                            "provider_source_id": f"sumble:{contact_id}",
                            "source_url": "https://example.org/organization",
                            "artifact_ref": "artifact:sumble-people:1",
                            "evidence_span": f"Current title: {title}",
                        }
                    ],
                    "confidence": 0.95,
                    "verification_status": "supported",
                }
            ],
        }

    payload.update(
        {
            "requested_field_keys": [],
            "fields": [],
            "discovered_subjects": [
                discovered("22222222-2222-4222-8222-222222222221", "VP Operations"),
                discovered("22222222-2222-4222-8222-222222222222", "Chief Financial Officer"),
            ],
        }
    )
    result = PersistedResearchToolResult.model_validate(payload)
    assert len(result.discovered_subjects) == 2
    assert {subject.parent_account_id for subject in result.discovered_subjects} == {
        result.target_entity_id
    }

    payload["discovered_subjects"][1]["parent_account_id"] = "33333333-3333-4333-8333-333333333333"
    with pytest.raises(ValidationError, match="different parent account"):
        PersistedResearchToolResult.model_validate(payload)


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
    assert fixture["contract_version"] == "m8d-r0-v7"
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
