"""Evidence receipt v2 previews what came back and says when nothing did.

Production 2026-10-06: each acquire_research_evidence receipt carried two UUIDs and a path, so
the agent spent a model round reading /research/operations/<id>/0.json just to see what came
back, and an empty search or a failed fetch was reported as "completed".
"""

import json

from clue_agents.execution import SPILL_THRESHOLD_BYTES
from clue_api.arv2.quality_provider_tools import (
    PREVIEW_MAX_BYTES,
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


def test_a_large_result_keeps_every_entry_and_stays_inline():
    """Founder ruling 2026-10-10: every entry is shown. Snippets (then titles) shorten only as far
    as needed to keep the receipt under the spill line, so it is never swapped for a file pointer.
    """
    value = {
        "n_results": 40,
        "results": [
            {"url": f"https://x.test/{i}", "title": "T" * 400, "text": "w" * 5000}
            for i in range(40)
        ],
    }
    hits, count, _ = receipt_preview(value)
    assert count == 40
    assert [h["url"] for h in hits] == [f"https://x.test/{i}" for i in range(40)]
    assert len(json.dumps(hits)) <= PREVIEW_MAX_BYTES < SPILL_THRESHOLD_BYTES


def test_a_typical_search_keeps_full_snippets():
    value = {
        "n_results": 10,
        "results": [
            {"url": f"https://x.test/{i}", "title": f"Result {i}", "text": "word " * 200}
            for i in range(10)
        ],
    }
    hits, _, _ = receipt_preview(value)
    assert len(hits) == 10
    assert all(len(h["snippet"]) == 300 for h in hits)


def _run3_navigation() -> dict:
    """Run 3 (2026-10-09): ten Exa results saved as twenty-one files — the response record, then a
    provider record and a page snapshot per result. The 6sense story was result 6."""
    urls = [f"https://www.linkedin.com/posts/emilywall_{i}" for i in range(10)]
    urls[5] = "https://6sense.com/customer-stories/dialpad-elevates-digital-abm-with-6sense"
    sources = [{"kind": "provider_record", "path": "/evidence/0025-provider-record.json"}]
    for i, url in enumerate(urls):
        sources.append(
            {
                "kind": "provider_record",
                "url": url,
                "title": f"R{i}",
                "path": f"/evidence/{26 + 2 * i:04d}-record.json",
            }
        )
        sources.append(
            {
                "kind": "web_snapshot",
                "url": url,
                "title": f"R{i}",
                "path": f"/evidence/{27 + 2 * i:04d}-page.json",
            }
        )
    return {"sources": sources, "urls": urls}


def test_every_search_result_is_previewed_once_with_its_snippet_and_page_path():
    nav = _run3_navigation()
    value = {
        "result_ref": "r",
        "n_results": 10,
        "results": [
            {"url": url, "title": f"R{i}", "text_head": f"Highlight of result {i}."}
            for i, url in enumerate(nav["urls"])
        ],
        "source_navigation": {"sources": nav["sources"]},
    }
    hits, count, _ = receipt_preview(value)
    assert count == 10
    assert [h["url"] for h in hits] == nav["urls"]
    assert hits[5]["snippet"] == "Highlight of result 5."
    assert hits[5]["path"] == "/evidence/0037-page.json"  # the page text, not the record


def test_without_result_rows_each_source_appears_once_and_the_response_record_is_left_out():
    nav = _run3_navigation()
    hits, _, _ = receipt_preview(
        {"result_ref": "r", "source_navigation": {"sources": nav["sources"]}}
    )
    assert [h["url"] for h in hits] == nav["urls"]
    assert hits[5]["path"] == "/evidence/0037-page.json"


def test_a_deep_report_lists_every_source_after_its_opening():
    value = {
        "report": "Dialpad's CMO left in Sept 2025. " * 40,
        "n_results": 30,
        "results": [{"url": f"https://s.test/{i}", "title": f"S{i}"} for i in range(30)],
    }
    hits, _, _ = receipt_preview(value)
    assert hits[0]["title"] == "Report"
    assert [h["url"] for h in hits[1:]] == [f"https://s.test/{i}" for i in range(30)]


def test_v2_is_a_new_version_and_v1_is_unchanged():
    assert AcquireResearchTool.version == "1"
    assert AcquireResearchTool.output_model is AcquireResearchReceipt
    assert AcquireResearchToolV2.version == "2"
    assert AcquireResearchToolV2.output_model is AcquireResearchReceiptV2
    assert "empty" in AcquireResearchReceiptV2.model_json_schema()["properties"]["status"]["enum"]


def test_a_body_that_is_not_a_result_list_is_never_reported_empty():
    """Review I3: an enrichment profile or a queued job came back with something."""
    for value in (
        {"profile": {"full_name": "Ana Ruiz", "title": "ABM Manager"}, "source_id": "s1"},
        {"state": "queued", "operation_id": "op"},
        {"item_id": "m1", "transcript_path": "/evidence/0003-podcast.json"},
    ):
        assert receipt_preview(value)[2] is False, value
