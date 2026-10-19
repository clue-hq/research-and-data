"""A site (Puck) reads like a web page to the exit judge and in the turn summaries (Wave 2)."""

from __future__ import annotations

from typing import Any

from clue_api.chat.schemas import DesignArtifactWire
from clue_api.design_leg_wiring import (
    _assistant_summary,
    _card_account_id,
    batch_summary,
    clarification_sentence,
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
            "result": {
                "status": "succeeded",
                "doc_kind": "site",
                "current_version": 4,
                "summary": "Built the page.",
            },
        }
    )
    assert (
        summary
        == "Design turn succeeded on website document doc_site (now version 4): Built the page."
    )


def test_batch_summary_names_a_site_turns_version_once() -> None:
    items = [
        (
            {"title": "Syracuse site", "position": 0},
            {
                "status": "succeeded",
                "document_id": "doc_site",
                "result": {"status": "succeeded", "doc_kind": "site", "current_version": 4},
            },
        ),
        (
            {"title": "Apollo ad", "position": 1},
            {
                "status": "succeeded",
                "result": {
                    "status": "proposed",
                    "acceptance_scope": "design",
                    "current_version": 2,
                },
            },
        ),
    ]
    lines = batch_summary(items).splitlines()
    assert (
        lines[0]
        == "Syracuse site: Design turn succeeded on website document doc_site (now version 4)."
    )
    assert lines[1].startswith("Apollo ad: Design saved and accepted") and "version 2" in lines[1]


def test_a_site_document_gets_its_account_card() -> None:
    assert _card_account_id({"doc_kind": "site", "account_id": "acc_1"}) == "acc_1"
    assert _card_account_id({"doc_kind": "web", "account_id": "acc_2"}) == "acc_2"
    assert _card_account_id({"doc_kind": "scene", "account_id": "acc_3"}) is None
    assert _card_account_id(None) is None


def test_the_wire_models_accept_site() -> None:
    wire = DesignArtifactWire(
        id="d",
        project_id="p",
        document_id="d",
        kind="site",
        title="T",
        status="draft",
        current_version_id="1",
    )
    assert wire.kind == "site"
    artifact = AccountArtifact(
        id="d",
        title="T",
        type="site",
        thumbnail_path="/api/clue/design/documents/d/thumbnail?v=1",
        last_edited_label="Last edited Oct 11, 2026",
    )
    assert artifact.type == "site"


def _clarification_run(doc_kind: str, document_id: str) -> dict[str, Any]:
    """A terminal run that stopped to ask (spec 2026-09-20 §2.2): the questions
    ``clarification_sentence`` reads, beside the version and note a turn result also carries."""
    return {
        "status": "succeeded",
        "document_id": document_id,
        "result": {
            "schema_version": 1,
            "doc_kind": doc_kind,
            "status": "clarification_requested",
            "current_version": 4,
            "summary": "I need one answer first.",
            "clarification": {
                "questions": [
                    {
                        "id": "audience",
                        "question": "Who is the page for?",
                        "default": "The district's CFO",
                    },
                    {
                        "id": "proof",
                        "question": "Which proof point should lead?",
                        "default": "The 12% stat",
                    },
                ]
            },
        },
    }


def test_a_site_turn_that_stopped_to_ask_reads_as_its_question() -> None:
    """Contract 7: a site turn may stop to ask. It designed nothing, so its thread record is the
    question — alone and in a batch line — never "Design turn clarification_requested on …"."""
    site = _clarification_run("site", "doc_site")
    asked = clarification_sentence(site["result"])
    assert asked == (
        "Asked you 2 questions before designing: Who is the page for?; "
        "Which proof point should lead?."
    )
    assert _assistant_summary(site) == asked
    assert batch_summary([({"title": "Syracuse site"}, site)]) == f"Syracuse site: {asked}"

    # A web turn's summary is unchanged (pinned from before this change).
    web = _clarification_run("web", "doc_web")
    assert _assistant_summary(web) == (
        "Design turn clarification_requested on website document doc_web (now version 4): "
        "I need one answer first."
    )
