"""A site (Puck) reads like a web page to the exit judge and in the turn summaries (Wave 2)."""

from __future__ import annotations

from clue_api.chat.schemas import DesignArtifactWire
from clue_api.design_leg_wiring import (
    _assistant_summary,
    _card_account_id,
    batch_summary,
    design_kind_label,
)
from clue_api.frontend_read.contract_v1 import AccountArtifact


def test_a_site_is_a_web_page_to_the_exit_judge() -> None:
    assert design_kind_label("site") == "web page"
    assert design_kind_label("web") == "web page"
    assert design_kind_label("scene") == "scene ad"
    assert design_kind_label("ad") == "scene ad"
    assert design_kind_label(None) == "scene ad"


def test_a_site_turn_reads_back_like_a_web_turn() -> None:
    summary = _assistant_summary(
        {
            "status": "succeeded",
            "document_id": "doc_site",
            "result": {"status": "succeeded", "doc_kind": "site", "current_version": 4, "summary": "Built the page."},
        }
    )
    assert summary == "Design turn succeeded on website document doc_site (now version 4): Built the page."


def test_batch_summary_names_a_site_turns_version_once() -> None:
    items = [
        (
            {"title": "Syracuse site", "position": 0},
            {"status": "succeeded", "document_id": "doc_site", "result": {"status": "succeeded", "doc_kind": "site", "current_version": 4}},
        ),
        (
            {"title": "Apollo ad", "position": 1},
            {"status": "succeeded", "result": {"status": "proposed", "acceptance_scope": "design", "current_version": 2}},
        ),
    ]
    lines = batch_summary(items).splitlines()
    assert lines[0] == "Syracuse site: Design turn succeeded on website document doc_site (now version 4)."
    assert lines[1].startswith("Apollo ad: Design saved and accepted") and "version 2" in lines[1]


def test_a_site_document_gets_its_account_card() -> None:
    assert _card_account_id({"doc_kind": "site", "account_id": "acc_1"}) == "acc_1"
    assert _card_account_id({"doc_kind": "web", "account_id": "acc_2"}) == "acc_2"
    assert _card_account_id({"doc_kind": "scene", "account_id": "acc_3"}) is None
    assert _card_account_id(None) is None


def test_the_wire_models_accept_site() -> None:
    wire = DesignArtifactWire(id="d", project_id="p", document_id="d", kind="site", title="T", status="draft", current_version_id="1")
    assert wire.kind == "site"
    artifact = AccountArtifact(
        id="d", title="T", type="site", thumbnail_path="/api/clue/design/documents/d/thumbnail?v=1",
        last_edited_label="Last edited Oct 11, 2026",
    )
    assert artifact.type == "site"
