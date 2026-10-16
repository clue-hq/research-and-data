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


def _site_run(outcome: str, summary: str, *, version: int = 3) -> dict:
    return {
        "status": "succeeded",
        "document_id": "doc_1",
        "result": {
            "doc_kind": "site",
            "status": "applied",
            "outcome": outcome,
            "current_version": version,
            "saved_version": None,
            "summary": summary,
        },
    }


def test_a_site_turn_that_saved_nothing_says_so_instead_of_echoing_the_agent() -> None:
    # K4-1: the agent's last words said "Built the page", but its save changed nothing.
    run = _site_run("unchanged", "Built the page with a hero and pricing.")
    assert (
        _assistant_summary(run)
        == "Design turn applied on website document doc_1 (still version 3): no changes were saved."
    )


def test_a_saved_site_turn_with_an_explicit_outcome_still_echoes_the_agent() -> None:
    run = _site_run("saved", "Built the page.", version=4)
    run["result"]["saved_version"] = 4
    assert (
        _assistant_summary(run)
        == "Design turn applied on website document doc_1 (now version 4): Built the page."
    )


def test_a_site_turn_already_saved_by_an_earlier_attempt_reads_the_results_own_message() -> None:
    message = (
        "This request was already saved as version 3 by an earlier attempt, "
        "so this attempt's changes were not saved."
    )
    run = _site_run("already_saved", message)
    sentence = _assistant_summary(run)
    assert sentence == f"Design turn applied on website document doc_1 (now version 3): {message}"
    assert "Built" not in sentence


def test_a_batch_line_for_an_unchanged_site_says_nothing_was_saved() -> None:
    saved = _site_run("saved", "Built the page.", version=4)
    unchanged = _site_run("unchanged", "Built the page.")
    unchanged["document_id"] = "doc_2"
    lines = batch_summary([({"title": "Page A"}, saved), ({"title": "Page B"}, unchanged)])
    assert lines == (
        "Page A: Design turn applied on website document doc_1 (now version 4): Built the page.\n"
        "Page B: Design turn applied on website document doc_2 (still version 3): "
        "no changes were saved."
    )
