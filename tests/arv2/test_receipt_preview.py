"""Evidence receipt v2 previews what came back and says when nothing did.

Production 2026-10-06: each acquire_research_evidence receipt carried two UUIDs and a path, so
the agent spent a model round reading /research/operations/<id>/0.json just to see what came
back, and an empty search or a failed fetch was reported as "completed".
"""

import json

from clue_api.arv2.quality_provider_tools import (
    AcquireResearchReceipt,
    AcquireResearchReceiptV2,
    AcquireResearchTool,
    AcquireResearchToolV2,
    receipt_preview,
)

NAV = {
    "operation_id": "op",
    "evidence_index_path": "/evidence/index.json",
    "sources": [
        {
            "path": "/evidence/0001-dialpad-careers.json",
            "url": "https://dialpad.com/careers/abm",
            "title": "ABM Manager — Dialpad",
            "published_at": "2026-09-01",
        }
    ],
}


def test_a_search_previews_titles_links_paths_and_snippets():
    value = {
        "result_ref": "r",
        "n_results": 1,
        "results": [
            {
                "url": "https://dialpad.com/careers/abm",
                "title": "ABM Manager — Dialpad",
                "text": "We are hiring an ABM manager to run field programmes. " * 20,
            }
        ],
        "source_navigation": NAV,
    }
    hits, count, empty = receipt_preview(value)
    assert count == 1 and not empty
    assert hits[0]["path"] == "/evidence/0001-dialpad-careers.json"
    assert hits[0]["url"] == "https://dialpad.com/careers/abm"
    assert hits[0]["published"] == "2026-09-01"
    assert 0 < len(hits[0]["snippet"]) <= 300


def test_navigation_alone_still_previews_the_sources():
    hits, count, empty = receipt_preview({"result_ref": "r", "source_navigation": NAV})
    assert [h["title"] for h in hits] == ["ABM Manager — Dialpad"] and not empty


def test_nothing_back_is_empty():
    assert receipt_preview({"result_ref": "r", "n_results": 0})[2]
    assert receipt_preview({"result_ref": "r", "results": [], "statuses": [{"status": "error"}]})[2]
    assert receipt_preview({"report": "", "gaps": ["deep_report_empty_review_returned_sources"]})[2]


def test_a_deep_report_previews_its_opening():
    hits, _, empty = receipt_preview({"report": "Dialpad's CMO left in Sept 2025. " * 40})
    assert not empty and hits[0]["snippet"].startswith("Dialpad's CMO left")


def test_the_preview_is_bounded_well_under_the_spill_threshold():
    value = {
        "n_results": 40,
        "results": [
            {"url": f"https://x.test/{i}", "title": "T" * 400, "text": "w" * 5000}
            for i in range(40)
        ],
    }
    hits, count, _ = receipt_preview(value)
    assert count == 40 and len(hits) <= 8
    assert len(json.dumps(hits)) <= 6 * 1024


def test_v2_is_a_new_version_and_v1_is_unchanged():
    assert AcquireResearchTool.version == "1"
    assert AcquireResearchTool.output_model is AcquireResearchReceipt
    assert AcquireResearchToolV2.version == "2"
    assert AcquireResearchToolV2.output_model is AcquireResearchReceiptV2
    assert "empty" in AcquireResearchReceiptV2.model_json_schema()["properties"]["status"]["enum"]
