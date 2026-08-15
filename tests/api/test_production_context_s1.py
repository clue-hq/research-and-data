"""Pure API-seam checks for the S1 envelope and split-card DSAR reach."""

from __future__ import annotations

from uuid import UUID

from clue_api.agent_turn_fleet_wiring import project_conversation_card_payload
from clue_api.stage0_card_dsar import STAGE0_CARD_QUOTE_BINDING_KIND, stage0_card_subject_bindings
from clue_projections.production_context import (
    ProjectConversationCard,
    ProjectProductSelectionStatus,
    Stage0ProductSelection,
    Stage0ProjectFieldProposals,
    Stage0ProjectStateCard,
    Stage0ProjectStateLineage,
)
from clue_projections.stage0 import (
    Stage0CardIcp,
    Stage0CardInterview,
    Stage0CardReadiness,
    Stage0CardSelection,
    Stage0CardStatement,
)


def test_production_envelope_is_v2_and_defaults_to_honest_s1_unavailability() -> None:
    payload = project_conversation_card_payload(
        workspace_id="workspace-one",
        project_id="project-one",
        project_name="Project One",
        project_status="active",
        brand_id="brand-one",
        product_id=None,
        thread_id="thread-one",
    )
    card = ProjectConversationCard.model_validate(payload)
    assert payload["schema_version"] == "2"
    assert card.project.confirmed_product_id is None
    assert payload["context_availability"] == {
        "client_knowledge": "unavailable",
        "stage0_project_state": "unavailable",
        "brand_profile": "minimal",
        "product_profile": "unavailable",
    }
    assert "client_knowledge_base" not in payload


def test_split_project_state_retains_statement_level_dsar_bindings() -> None:
    client_entity_id = UUID("00000000-0000-4000-8000-000000000001")
    statement_id = "00000000-0000-4000-8000-000000000002"
    card = Stage0ProjectStateCard(
        compiler_policy_version="stage0-project-state-policy-v1",
        product_selection=Stage0ProductSelection(status=ProjectProductSelectionStatus.UNSELECTED),
        field_proposals=Stage0ProjectFieldProposals(),
        interview=Stage0CardInterview(
            current_effective_statements=(
                Stage0CardStatement(
                    statement_id=statement_id,
                    route_key="campaign_goal",
                    route_kind="project_state",
                    quoted_text="Win the neurosurgery market",
                    quote_truncated=False,
                ),
            ),
            selection=Stage0CardSelection(
                included=1,
                total_effective=1,
                deduped_count=0,
            ),
            unmapped_count=0,
            superseded_count=0,
        ),
        readiness=Stage0CardReadiness(latest_by_gate=(), ledger_length=0),
        icp=Stage0CardIcp(confirmed=(), proposals_pending=False, proposals_stale=False),
        omissions=(),
        compiled_from=Stage0ProjectStateLineage(
            client_knowledge_sha256="sha256:" + "1" * 64,
            statement_selection_digest="sha256:" + "2" * 64,
            readiness_decision_ids=(),
            confirmed_icps=(),
            compiler_policy_version="stage0-project-state-policy-v1",
            source_policy_version="stage0-card-policy-v1",
        ),
    )
    assert set(stage0_card_subject_bindings(card=card, base=((client_entity_id, "context"),))) == {
        (client_entity_id, "context"),
        (UUID(statement_id), STAGE0_CARD_QUOTE_BINDING_KIND),
    }
