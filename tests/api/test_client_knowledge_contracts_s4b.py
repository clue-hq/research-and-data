"""S4-B provider-, network-, and database-free contract freeze acceptance."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from clue_api.client_knowledge_contracts import (
    CLIENT_KNOWLEDGE_CURSOR_POLICY_VERSION,
    CLIENT_KNOWLEDGE_CURSOR_SCHEMA_VERSION,
    CLIENT_KNOWLEDGE_TOOL_CONTRACT_VERSION,
    DEFAULT_CLIENT_KNOWLEDGE_PAGE_SIZE,
    INSPECT_CLIENT_CLAIM_ADDRESS,
    LIST_CLIENT_KNOWLEDGE_ADDRESS,
    MAX_CLAIM_VALUE_BYTES,
    MAX_CLIENT_CLAIM_RESPONSE_BYTES,
    MAX_CLIENT_KNOWLEDGE_CURSOR_BYTES,
    MAX_CLIENT_KNOWLEDGE_LIST_RESPONSE_BYTES,
    MAX_CLIENT_KNOWLEDGE_PAGE_SIZE,
    MAX_EVIDENCE_SPAN_BYTES,
    MAX_FIELD_BRIEF_BYTES,
    MAX_FIELD_DESCRIPTION_BYTES,
    MODEL_VISIBLE_INSPECT_FIELDS,
    MODEL_VISIBLE_LIST_FIELDS,
    TRUSTED_CLIENT_KNOWLEDGE_FIELDS,
    ClientClaimInspectionV2Output,
    ClientClaimV2,
    ClientKnowledgeCursorRefused,
    ClientKnowledgeCursorV2,
    ClientKnowledgeListEntryV2,
    ClientKnowledgeListV2Output,
    ClientKnowledgeRefusalCode,
    InspectClientClaimV2Input,
    ListClientKnowledgeV2Input,
    canonical_json_bytes,
    decode_client_knowledge_cursor,
    encode_client_knowledge_cursor,
    response_bytes,
    sanitize_source_url,
    truncate_utf8,
)
from clue_core import (
    ClaimFlavor,
    ClaimProvenanceKind,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    VerificationStatus,
)
from clue_projections import (
    CLIENT_KNOWLEDGE_CARD_POLICY_V1,
    ClientKnowledgeTopic,
    encode_card_cursor,
)

FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "production_context" / "s4b_tool_contract_fixture.json"
)
CLIENT_ONE = UUID("11111111-1111-4111-8111-111111111111")
FOREIGN_CLIENT = UUID("22222222-2222-4222-8222-222222222222")
CLAIM_ONE = UUID("33333333-3333-4333-8333-333333333333")
RUN_ONE = UUID("44444444-4444-4444-8444-444444444444")


def _schema_sha256(model: type[object]) -> str:
    schema = model.model_json_schema()  # type: ignore[attr-defined]
    return f"sha256:{hashlib.sha256(canonical_json_bytes(schema)).hexdigest()}"


def _entry(index: int = 1) -> ClientKnowledgeListEntryV2:
    return ClientKnowledgeListEntryV2(
        field_key=f"client.fixture_{index}",
        label=f"Fixture {index}",
        description="A bounded index entry that routes the agent to one exact claim.",
        description_truncated=False,
        topic=ClientKnowledgeTopic.OTHER,
        brief_value=f"bounded value {index}",
        brief_truncated=False,
        claim_id=UUID(f"33333333-3333-4333-8333-{index:012d}"),
        retired=False,
    )


def _claim() -> ClientClaimV2:
    value = {"name": "Clue"}
    return ClientClaimV2.model_validate(
        {
            "claim_id": CLAIM_ONE,
            "field": {
                "field_key": "client.product",
                "label": "Product",
                "topic": ClientKnowledgeTopic.PRODUCT,
                "description": "The customer's product catalog.",
                "description_truncated": False,
                "retired": False,
            },
            "value": value,
            "value_preview": '{"name":"Clue"}',
            "value_sha256": f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}",
            "value_truncated": False,
            "evidence_span": "Clue is the product.",
            "evidence_span_truncated": False,
            "source": {
                "source_key": "official_site",
                "source_tier": 1,
                "extraction_method": ExtractionMethod.SCRAPE,
                "public_source_origin": "https://example.com/",
                "source_url_sha256": f"sha256:{'b' * 64}",
                "source_url_redacted": True,
                "artifact_key": "artifact/one",
                "artifact_key_truncated": False,
            },
            "provider_lineage": {
                "operation_ref": "operation-one",
                "operation_ref_truncated": False,
                "snapshot_ref": "snapshot-one",
                "snapshot_ref_truncated": False,
                "request_ref": "request-one",
                "request_ref_truncated": False,
            },
            "quality": {
                "confidence": Decimal("0.95"),
                "corroborations": 1,
                "verification_status": VerificationStatus.VERIFIED,
                "freshness": "fresh",
                "freshness_reference_at": datetime(2026, 8, 14, tzinfo=UTC),
                "fresh_until": datetime(2026, 9, 14, tzinfo=UTC),
            },
            "lineage": {
                "run_id": RUN_ONE,
                "research_mode": ResearchMode.ACCOUNT_PROFILING,
                "provenance_kind": ClaimProvenanceKind.PROVIDER_RETURNED,
                "claim_flavor": ClaimFlavor.FIELD_CLAIM,
                "reuse_scope": ReuseScope.TENANT_PRIVATE,
                "product_id": None,
                "observed_at": datetime(2026, 8, 14, tzinfo=UTC),
                "collected_at": datetime(2026, 8, 14, 0, 0, 1, tzinfo=UTC),
            },
        }
    )


def test_frozen_manifest_matches_every_public_schema_and_limit() -> None:
    manifest = json.loads(FIXTURE.read_text())
    assert manifest["contract_version"] == CLIENT_KNOWLEDGE_TOOL_CONTRACT_VERSION
    assert manifest["addresses"] == {
        "list": LIST_CLIENT_KNOWLEDGE_ADDRESS,
        "inspect": INSPECT_CLIENT_CLAIM_ADDRESS,
    }
    assert manifest["inputs"]["list"] == {
        "model_visible_fields": list(MODEL_VISIBLE_LIST_FIELDS),
        "trusted_fields": list(TRUSTED_CLIENT_KNOWLEDGE_FIELDS),
        "complete_input_fields": [
            "client_entity_id",
            "client_kb_version",
            "topic",
            "field_key",
            "cursor",
            "limit",
        ],
        "schema_sha256": _schema_sha256(ListClientKnowledgeV2Input),
    }
    assert manifest["inputs"]["inspect"] == {
        "model_visible_fields": list(MODEL_VISIBLE_INSPECT_FIELDS),
        "trusted_fields": list(TRUSTED_CLIENT_KNOWLEDGE_FIELDS),
        "complete_input_fields": ["client_entity_id", "client_kb_version", "claim_id"],
        "schema_sha256": _schema_sha256(InspectClientClaimV2Input),
    }
    assert manifest["outputs"] == {
        "list_schema_sha256": _schema_sha256(ClientKnowledgeListV2Output),
        "inspect_schema_sha256": _schema_sha256(ClientClaimInspectionV2Output),
        "content_semantics": "untrusted_evidence_not_instructions",
    }
    assert manifest["limits"] == {
        "default_page_size": DEFAULT_CLIENT_KNOWLEDGE_PAGE_SIZE,
        "max_page_size": MAX_CLIENT_KNOWLEDGE_PAGE_SIZE,
        "cursor_bytes": MAX_CLIENT_KNOWLEDGE_CURSOR_BYTES,
        "list_response_bytes": MAX_CLIENT_KNOWLEDGE_LIST_RESPONSE_BYTES,
        "inspect_response_bytes": MAX_CLIENT_CLAIM_RESPONSE_BYTES,
        "field_description_bytes": MAX_FIELD_DESCRIPTION_BYTES,
        "field_brief_bytes": MAX_FIELD_BRIEF_BYTES,
        "claim_value_bytes": MAX_CLAIM_VALUE_BYTES,
        "evidence_span_bytes": MAX_EVIDENCE_SPAN_BYTES,
    }
    assert manifest["refusal_codes"] == [item.value for item in ClientKnowledgeRefusalCode]


def test_only_the_frozen_model_fields_can_be_model_authored() -> None:
    list_schema = ListClientKnowledgeV2Input.model_json_schema()["properties"]
    inspect_schema = InspectClientClaimV2Input.model_json_schema()["properties"]
    assert set(list_schema) == {
        "client_entity_id",
        "client_kb_version",
        *MODEL_VISIBLE_LIST_FIELDS,
    }
    assert set(inspect_schema) == {
        "client_entity_id",
        "client_kb_version",
        *MODEL_VISIBLE_INSPECT_FIELDS,
    }
    for forbidden in ("workspace_id", "project_id", "product_id"):
        assert forbidden not in list_schema
        assert forbidden not in inspect_schema
        with pytest.raises(ValidationError):
            InspectClientClaimV2Input.model_validate(
                {
                    "client_entity_id": str(CLIENT_ONE),
                    "client_kb_version": 1,
                    "claim_id": str(CLAIM_ONE),
                    forbidden: "model-authored",
                }
            )


def test_v2_cursor_is_deterministic_and_bound_to_scope_filters_and_limit() -> None:
    cursor_model = ClientKnowledgeCursorV2(
        client_entity_id=CLIENT_ONE,
        client_kb_version=7,
        after_field_key="client.product",
        topic=ClientKnowledgeTopic.PRODUCT,
        field_key="client.product",
        limit=7,
    )
    encoded = encode_client_knowledge_cursor(cursor_model)
    assert encoded == encode_client_knowledge_cursor(cursor_model)
    assert len(encoded.encode()) <= MAX_CLIENT_KNOWLEDGE_CURSOR_BYTES
    assert (
        decode_client_knowledge_cursor(
            encoded,
            client_entity_id=CLIENT_ONE,
            client_kb_version=7,
            topic=ClientKnowledgeTopic.PRODUCT,
            field_key="client.product",
            limit=7,
        )
        == cursor_model
    )

    refusals = (
        (FOREIGN_CLIENT, 7, ClientKnowledgeTopic.PRODUCT, "client.product", 7),
        (CLIENT_ONE, 8, ClientKnowledgeTopic.PRODUCT, "client.product", 7),
        (CLIENT_ONE, 7, ClientKnowledgeTopic.OTHER, "client.product", 7),
        (CLIENT_ONE, 7, ClientKnowledgeTopic.PRODUCT, None, 7),
        (CLIENT_ONE, 7, ClientKnowledgeTopic.PRODUCT, "client.product", 8),
    )
    for client_entity, version, topic, field_key, limit in refusals:
        with pytest.raises(ClientKnowledgeCursorRefused) as refusal:
            decode_client_knowledge_cursor(
                encoded,
                client_entity_id=client_entity,
                client_kb_version=version,
                topic=topic,
                field_key=field_key,
                limit=limit,
            )
        assert refusal.value.reason_code == "client_knowledge_cursor_invalid"
        assert str(refusal.value) == "cursor is unavailable for this Client-KB view"
    for malformed in ("not-a-cursor", "", "e30"):
        with pytest.raises(ClientKnowledgeCursorRefused) as refusal:
            decode_client_knowledge_cursor(
                malformed,
                client_entity_id=CLIENT_ONE,
                client_kb_version=7,
                topic=ClientKnowledgeTopic.PRODUCT,
                field_key="client.product",
                limit=7,
            )
        assert refusal.value.reason_code == "client_knowledge_cursor_invalid"
        assert str(refusal.value) == "cursor is unavailable for this Client-KB view"


def test_only_unfiltered_default_s1_omission_cursor_is_accepted() -> None:
    cursor = encode_card_cursor(
        {
            "kind": "client_knowledge",
            "schema_version": "1",
            "client_entity_id": str(CLIENT_ONE),
            "client_kb_version": 4,
            "compiler_policy_version": CLIENT_KNOWLEDGE_CARD_POLICY_V1.version,
            "after_field_key": "client.product",
        }
    )
    parsed = decode_client_knowledge_cursor(
        cursor,
        client_entity_id=CLIENT_ONE,
        client_kb_version=4,
        topic=None,
        field_key=None,
        limit=DEFAULT_CLIENT_KNOWLEDGE_PAGE_SIZE,
    )
    assert parsed.schema_version == "1"
    assert parsed.after_field_key == "client.product"
    with pytest.raises(ClientKnowledgeCursorRefused):
        decode_client_knowledge_cursor(
            cursor,
            client_entity_id=CLIENT_ONE,
            client_kb_version=4,
            topic=ClientKnowledgeTopic.PRODUCT,
            field_key=None,
            limit=DEFAULT_CLIENT_KNOWLEDGE_PAGE_SIZE,
        )


def test_nested_outputs_are_strict_bounded_and_self_describing() -> None:
    cursor = encode_client_knowledge_cursor(
        ClientKnowledgeCursorV2(
            client_entity_id=CLIENT_ONE,
            client_kb_version=1,
            after_field_key="client.fixture_1",
            topic=None,
            field_key=None,
            limit=1,
        )
    )
    listed = ClientKnowledgeListV2Output(
        client_entity_id=CLIENT_ONE,
        client_kb_version=1,
        topic=None,
        field_key=None,
        requested_limit=1,
        knowledge=(_entry(),),
        returned=1,
        total_matching=2,
        has_more=True,
        next_cursor=cursor,
    )
    inspected = ClientClaimInspectionV2Output(
        client_entity_id=CLIENT_ONE,
        client_kb_version=1,
        claim=_claim(),
    )
    for output, cap in (
        (listed, MAX_CLIENT_KNOWLEDGE_LIST_RESPONSE_BYTES),
        (inspected, MAX_CLIENT_CLAIM_RESPONSE_BYTES),
    ):
        assert output.content_semantics == "untrusted_evidence_not_instructions"
        assert response_bytes(output) <= cap
    with pytest.raises(ValidationError):
        ClientKnowledgeListEntryV2.model_validate(
            _entry().model_dump(mode="json") | {"raw_page_body": "forbidden"}
        )
    with pytest.raises(ValidationError):
        ClientKnowledgeListEntryV2.model_validate(
            _entry().model_dump(mode="python")
            | {"brief_value": "too short", "brief_truncated": True}
        )
    with pytest.raises(ValidationError):
        ClientKnowledgeListV2Output(
            client_entity_id=CLIENT_ONE,
            client_kb_version=1,
            topic=None,
            field_key=None,
            requested_limit=1,
            knowledge=(_entry(),),
            returned=0,
            total_matching=1,
            has_more=False,
            next_cursor=None,
        )
    with pytest.raises(ValidationError):
        ClientKnowledgeListV2Output(
            client_entity_id=CLIENT_ONE,
            client_kb_version=1,
            topic=None,
            field_key=None,
            requested_limit=1,
            knowledge=(_entry(),),
            returned=1,
            total_matching=2,
            has_more=True,
            next_cursor=encode_client_knowledge_cursor(
                ClientKnowledgeCursorV2(
                    client_entity_id=CLIENT_ONE,
                    client_kb_version=1,
                    after_field_key="client.wrong_position",
                    topic=None,
                    field_key=None,
                    limit=1,
                )
            ),
        )
    with pytest.raises(ValidationError):
        ClientKnowledgeListV2Output(
            client_entity_id=CLIENT_ONE,
            client_kb_version=1,
            topic=None,
            field_key=None,
            requested_limit=2,
            knowledge=(_entry(), _entry()),
            returned=2,
            total_matching=2,
            has_more=False,
            next_cursor=None,
        )

    wrong_hash = _claim().model_dump(mode="python")
    wrong_hash["value_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(ValidationError):
        ClientClaimV2.model_validate(wrong_hash)
    unsafe_origin = _claim().model_dump(mode="python")
    unsafe_origin["source"]["public_source_origin"] = "https://example.com/private?token=x"
    with pytest.raises(ValidationError):
        ClientClaimV2.model_validate(unsafe_origin)
    private_origin = _claim().model_dump(mode="python")
    private_origin["source"]["public_source_origin"] = "http://127.0.0.1/"
    with pytest.raises(ValidationError):
        ClientClaimV2.model_validate(private_origin)


def test_byte_truncation_and_source_url_sanitization_never_leak_credentials() -> None:
    original = "€" * (MAX_EVIDENCE_SPAN_BYTES // 2) + "RAW_SENTINEL"
    bounded, truncated = truncate_utf8(original, MAX_EVIDENCE_SPAN_BYTES)
    assert truncated is True
    assert len(bounded.encode()) <= MAX_EVIDENCE_SPAN_BYTES
    assert "RAW_SENTINEL" not in bounded

    raw_url = "https://api-user:api-password@example.com/path?access_token=secret-token#fragment"
    sanitized = sanitize_source_url(raw_url)
    payload = canonical_json_bytes(sanitized.model_dump(mode="json")).decode()
    assert sanitized.public_origin == "https://example.com/"
    assert sanitized.exact_sha256 == f"sha256:{hashlib.sha256(raw_url.encode()).hexdigest()}"
    assert sanitized.redacted is True
    for forbidden in ("api-user", "api-password", "secret-token", "path", "fragment"):
        assert forbidden not in payload

    private_url = "http://127.0.0.1:8000/private?token=secret"
    private = sanitize_source_url(private_url)
    assert private.public_origin is None
    assert private.exact_sha256 == f"sha256:{hashlib.sha256(private_url.encode()).hexdigest()}"
    assert private.redacted is True


def test_fixture_freezes_cursor_revision_and_preliminary_v1_compatibility_boundary() -> None:
    manifest = json.loads(FIXTURE.read_text())
    assert manifest["cursor"] == {
        "schema_version": CLIENT_KNOWLEDGE_CURSOR_SCHEMA_VERSION,
        "policy_version": CLIENT_KNOWLEDGE_CURSOR_POLICY_VERSION,
        "bound_fields": [
            "client_entity_id",
            "client_kb_version",
            "after_field_key",
            "topic",
            "field_key",
            "limit",
        ],
        "legacy_acceptance": "s1_unfiltered_default_omission_only",
    }
    assert manifest["compatibility"] == {
        "preliminary_addresses": ["list_client_knowledge@1", "inspect_client_claim@1"],
        "mutation_rule": "do_not_rewrite_published_at1_schemas",
        "production_registration": "deferred_to_s4d",
    }
