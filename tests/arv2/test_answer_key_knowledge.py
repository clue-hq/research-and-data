"""The two stand-in brand-knowledge documents keep the shapes the onboarding plan fixes.

`ARV2-ONBOARDING-PLAN.md` §6.1 (ICP) and §6.2 (persona) are the machine contract the research lane
and the frontend read; a stand-in that drifts from them would let R2 build against the wrong shape
and pass. These checks are pure — they read the files the loader registers and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from clue_api.arv2.answer_key import ZAFRAN_MANIFEST, ZAFRAN_PRIORITY
from clue_api.arv2.answer_key_loader import KNOWLEDGE_DIR, _split_front_matter
from clue_core import Persona

KNOWLEDGE = Path(__file__).resolve().parents[2] / ".context" / KNOWLEDGE_DIR
ROLES = {persona.value for persona in Persona}


def _document(kind: str) -> tuple[dict, str]:
    (spec,) = [d for d in ZAFRAN_MANIFEST.documents if d.kind == kind]
    return _split_front_matter((KNOWLEDGE / spec.file).read_text(encoding="utf-8"))


def test_the_icp_document_carries_every_section_6_1_field() -> None:
    front, body = _document("icp-definition")
    assert front["kind"] == "icp-definition"
    assert front["icp_key"] == ZAFRAN_MANIFEST.icp_key
    assert front["version"] == 1 and front["status"] == "confirmed"
    assert {gate["key"] for gate in front["hard_gates"]} == {
        "geography",
        "stage",
        "hiring",
        "intent",
    }
    assert all({"key", "rule", "test"} <= set(gate) for gate in front["hard_gates"])
    assert len(front["exclusions"]) >= 5
    # The five-value persona vocabulary (master plan D8), each role with its title search keys.
    assert set(front["persona_map"]) == ROLES
    assert all(front["persona_map"][role]["titles"] for role in ROLES)
    for field in front["qualifier_fields"]:
        assert {"field_key", "description", "display"} <= set(field)
        assert field["field_key"] in ZAFRAN_PRIORITY, field["field_key"]
        assert field["display"] == "rail" or field["display"].startswith("section:")
    # Confirmation-only fields are stamped by the confirming act (the loader), never hand-written.
    assert not {"brand_id", "confirmed_by", "confirmed_at", "product_ids"} & set(front)
    assert "## 7. Qualification-floor verdict" in body


def test_the_persona_document_carries_every_section_6_2_field() -> None:
    front, body = _document("audience-persona")
    assert front["kind"] == "audience-persona"
    assert front["icp_key"] == ZAFRAN_MANIFEST.icp_key and front["icp_version"] == 1
    assert [p["role"] for p in front["personas"]] == [
        "economic_buyer",
        "champion",
        "user",
        "technical_evaluator",
        "blocker",
    ]
    for persona in front["personas"]:
        assert persona["titles"] and persona["buying_triggers"]
        assert isinstance(persona["evidence_urls"], list)
        assert f"## {persona['role']}" in body


def test_front_matter_round_trips_through_yaml() -> None:
    for spec in ZAFRAN_MANIFEST.documents:
        source = (KNOWLEDGE / spec.file).read_text(encoding="utf-8")
        front, _ = _split_front_matter(source)
        assert yaml.safe_load(yaml.safe_dump(front, sort_keys=False)) == front
