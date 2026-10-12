"""A site turn's thread record reads like a website's (Contract 7), never a scene ad's."""

from __future__ import annotations

from clue_api.design_leg_wiring import _assistant_summary, batch_summary


def test_a_saved_site_turn_names_the_website_and_its_version() -> None:
    run = {
        "status": "succeeded",
        "document_id": "doc_1",
        "result": {
            "doc_kind": "site",
            "status": "applied",
            "current_version": 3,
            "summary": "Built the page.",
        },
    }
    assert (
        _assistant_summary(run)
        == "Design turn applied on website document doc_1 (now version 3): Built the page."
    )


def test_a_batch_line_for_a_site_does_not_repeat_its_version() -> None:
    run = {
        "status": "succeeded",
        "document_id": "doc_1",
        "result": {
            "doc_kind": "site",
            "status": "applied",
            "current_version": 3,
            "summary": "Done.",
        },
    }
    line = batch_summary([({"title": "SCSD page"}, run)])
    assert line == "SCSD page: Design turn applied on website document doc_1 (now version 3): Done."
