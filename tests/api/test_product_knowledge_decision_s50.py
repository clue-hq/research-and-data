"""Provider/DB-free acceptance for the ratified S5.0 consumption decision."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from clue_api.client_knowledge_contracts import (
    MODEL_VISIBLE_INSPECT_FIELDS,
    MODEL_VISIBLE_LIST_FIELDS,
    TRUSTED_CLIENT_KNOWLEDGE_FIELDS,
)
from clue_api.product_knowledge_decision import (
    COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V2,
    INSPECT_PRODUCT_CLAIM_ADDRESS,
    LIST_PRODUCT_KNOWLEDGE_ADDRESS,
    MODEL_VISIBLE_INSPECT_PRODUCT_CLAIM_FIELDS,
    MODEL_VISIBLE_LIST_PRODUCT_KNOWLEDGE_FIELDS,
    PRODUCT_KNOWLEDGE_CONSUMPTION_DECISION_VERSION,
    S50_CONTEXT_STATES,
    S50_RATIFIED_DECISIONS,
    TRUSTED_PRODUCT_KNOWLEDGE_FIELDS,
    ProductKnowledgeContextState,
)
from clue_projections.production_context import (
    CLIENT_KNOWLEDGE_CARD_POLICY_V1,
    CLIENT_KNOWLEDGE_CARD_SCHEMA_VERSION,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests/fixtures/production_context/s50_product_knowledge_decision.json"
_CONTRACT = _ROOT / "docs/specs/FI-production-deepagent-context-S50-product-knowledge-contract.md"
_PARENT = _ROOT / "docs/specs/FI-production-deepagent-context-composition.md"
_MODULE = _ROOT / "platform/api/clue_api/product_knowledge_decision.py"


def _fixture() -> dict[str, object]:
    return json.loads(_FIXTURE.read_text())


def test_all_five_decisions_and_policy_version_are_frozen() -> None:
    fixture = _fixture()
    assert fixture["decision_version"] == PRODUCT_KNOWLEDGE_CONSUMPTION_DECISION_VERSION
    assert fixture["status"] == "ratified_contract_only"
    assert fixture["decisions"] == list(S50_RATIFIED_DECISIONS)
    scope = fixture["scope"]
    assert isinstance(scope, dict)
    assert scope == {
        "current_historical_policy": "company-account-wide-v1",
        "target_new_turn_policy": COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V2,
        "company_claim_selector": "product_id_is_null",
        "product_claim_selector": "product_id_equals_confirmed_project_product",
        "pin_fields": [
            "workspace_id",
            "client_entity_id",
            "company_client_kb_version",
            "confirmed_product_id",
            "product_kb_version",
            "knowledge_scope_policy_version",
        ],
        "snapshot_rule": "one_database_snapshot_before_cards_model_or_tools",
        "retry_rule": "reuse_exact_company_and_product_pair",
        "next_turn_rule": "new_turn_may_observe_newer_independent_versions",
    }


def test_product_tool_contract_has_no_model_authored_scope() -> None:
    fixture = _fixture()
    tools = fixture["tools"]
    assert isinstance(tools, dict)
    assert tools["product"] == [LIST_PRODUCT_KNOWLEDGE_ADDRESS, INSPECT_PRODUCT_CLAIM_ADDRESS]
    assert tools["product_list_model_fields"] == list(MODEL_VISIBLE_LIST_PRODUCT_KNOWLEDGE_FIELDS)
    assert tools["product_inspect_model_fields"] == list(MODEL_VISIBLE_INSPECT_PRODUCT_CLAIM_FIELDS)
    assert tools["product_trusted_fields"] == list(TRUSTED_PRODUCT_KNOWLEDGE_FIELDS)
    model_fields = set(MODEL_VISIBLE_LIST_PRODUCT_KNOWLEDGE_FIELDS) | set(
        MODEL_VISIBLE_INSPECT_PRODUCT_CLAIM_FIELDS
    )
    assert model_fields.isdisjoint(tools["model_forbidden_scope_fields"])
    assert {"workspace_id", "client_entity_id", "product_id", "product_kb_version"} <= set(
        TRUSTED_PRODUCT_KNOWLEDGE_FIELDS
    )


def test_s50_does_not_rewrite_client_card_v1_or_add_product_scope_to_s4() -> None:
    assert CLIENT_KNOWLEDGE_CARD_SCHEMA_VERSION == "1"
    assert CLIENT_KNOWLEDGE_CARD_POLICY_V1.version == "client-knowledge-card-policy-v1"
    assert MODEL_VISIBLE_LIST_FIELDS == ("topic", "field_key", "cursor", "limit")
    assert MODEL_VISIBLE_INSPECT_FIELDS == ("claim_id",)
    assert TRUSTED_CLIENT_KNOWLEDGE_FIELDS == (
        "workspace_id",
        "client_entity_id",
        "client_kb_version",
    )
    assert {"product_id", "product_kb_version"}.isdisjoint(TRUSTED_CLIENT_KNOWLEDGE_FIELDS)


def test_context_matrix_matches_executable_invariants() -> None:
    fixture = _fixture()
    parsed = tuple(
        ProductKnowledgeContextState.model_validate(item) for item in fixture["context_states"]
    )
    assert parsed == S50_CONTEXT_STATES

    unselected, missing, selected_a, selected_b = parsed
    assert unselected.confirmed_product_id is None
    assert "product_profile@1" not in unselected.cards
    assert "product_knowledge@1" not in unselected.cards
    assert missing.confirmed_product_id == "prd_a" and missing.product_kb_version is None
    assert "product_profile@1" in missing.cards
    assert "product_knowledge@1" not in missing.cards
    assert selected_a.confirmed_product_id != selected_b.confirmed_product_id
    assert selected_a.product_kb_version != selected_b.product_kb_version
    assert selected_a.company_client_kb_version == selected_b.company_client_kb_version


@pytest.mark.parametrize(
    "update",
    (
        {
            "name": "catalog_unselected",
            "confirmed_product_id": None,
            "product_kb_version": 1,
            "cards": (
                "client_knowledge@2",
                "project_conversation@2",
                "stage0_project_state@1",
                "product_knowledge@1",
            ),
            "model_tools": (
                "list_client_knowledge@2",
                "inspect_client_claim@2",
                LIST_PRODUCT_KNOWLEDGE_ADDRESS,
                INSPECT_PRODUCT_CLAIM_ADDRESS,
            ),
        },
        {
            "name": "selected_with_product_knowledge",
            "confirmed_product_id": "prd_a",
            "product_kb_version": 1,
            "cards": (
                "client_knowledge@2",
                "project_conversation@2",
                "stage0_project_state@1",
                "product_knowledge@1",
            ),
            "model_tools": (
                "list_client_knowledge@2",
                "inspect_client_claim@2",
                LIST_PRODUCT_KNOWLEDGE_ADDRESS,
                INSPECT_PRODUCT_CLAIM_ADDRESS,
            ),
        },
        {
            "name": "selected_without_product_knowledge",
            "confirmed_product_id": "prd_a",
            "product_kb_version": None,
            "cards": (
                "client_knowledge@2",
                "project_conversation@2",
                "stage0_project_state@1",
                "product_profile@1",
            ),
            "model_tools": (
                "list_client_knowledge@2",
                "inspect_client_claim@2",
                LIST_PRODUCT_KNOWLEDGE_ADDRESS,
            ),
        },
        {
            "name": "catalog_unselected",
            "confirmed_product_id": None,
            "product_kb_version": None,
            "cards": (
                "client_knowledge@2",
                "project_conversation@2",
                "stage0_project_state@1",
            ),
            "model_tools": (
                "list_client_knowledge@2",
                "inspect_client_claim@2",
                "model_selects_product@1",
            ),
        },
    ),
)
def test_incoherent_selected_product_states_fail_closed(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProductKnowledgeContextState(
            company_client_kb_version=7,
            **update,  # type: ignore[arg-type]
        )


def test_catalog_and_product_card_ownership_do_not_mix_detailed_facts_or_identity() -> None:
    fixture = _fixture()
    cards = fixture["cards"]
    assert isinstance(cards, dict)
    delta = cards["client_knowledge_v2_delta"]
    assert isinstance(delta, dict)
    assert delta["adds"] == "bounded_typed_product_catalog"
    assert set(delta["minimum_entry_fields"]) == {
        "product_id",
        "name",
        "short_description",
        "aliases",
        "status",
        "catalog_claim_id",
        "product_knowledge_available",
    }
    assert set(delta["forbidden"]) >= {
        "product_capabilities",
        "product_pricing",
        "product_integrations",
        "product_competitors",
        "product_customer_evidence",
    }
    assert cards["product_knowledge_repeats_product_profile_identity"] is False
    assert set(cards["product_profile_owner"]).isdisjoint(cards["product_knowledge_owner"])


def test_human_selection_and_catalog_sync_boundaries_are_explicit() -> None:
    fixture = _fixture()
    selection = fixture["selection"]
    sync = fixture["catalog_sync"]
    assert isinstance(selection, dict) and isinstance(sync, dict)
    assert selection == {
        "catalog_is_descriptive_not_authority": True,
        "agent_may_present_and_ask": True,
        "agent_may_confirm": False,
        "sole_write": "confirm_project_product@1",
        "human_authority_required": True,
    }
    assert sync["source_field"] == "client.product_catalog"
    assert sync["source_scope"] == "account_wide_only"
    assert sync["idempotent_replay"] is True
    assert sync["automatic_mutations_forbidden"] == ["rename", "merge", "archive", "delete"]
    assert sync["cross_workspace_match"] == sync["cross_brand_match"] == "refuse"


def test_s50_is_contract_complete_without_pretending_s5_runtime_is_live() -> None:
    fixture = _fixture()
    delivery = fixture["delivery"]
    assert isinstance(delivery, dict)
    assert delivery["s50_includes"] == [
        "decision_contract",
        "fixture",
        "adversarial_guards",
        "roadmap_delta",
    ]
    assert set(delivery["s50_excludes"]) == {
        "database_migration",
        "catalog_extraction",
        "catalog_synchronization",
        "client_knowledge_card_v2_runtime",
        "product_knowledge_card_runtime",
        "product_tool_registration",
        "production_policy_cutover",
    }
    contract = _CONTRACT.read_text()
    parent = _PARENT.read_text()
    for decision in range(1, 6):
        assert f"S50-D{decision}" in contract
    for checkpoint in "ABCDEF":
        assert f"S5-{checkpoint}" in contract
        assert f"S5-{checkpoint}" in parent
    assert "S5.0 — Product-knowledge consumption decision" in parent
    assert "implemented and contract-frozen 2026-08-15" in parent
    assert "S5.0 intentionally performs no migration" in parent


def test_executable_decision_module_has_no_provider_database_or_storage_import() -> None:
    tree = ast.parse(_MODULE.read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".", 1)[0])
    assert roots <= {"__future__", "typing", "pydantic"}
