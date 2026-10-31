from __future__ import annotations

import base64
import threading
import time
from contextvars import ContextVar
from copy import deepcopy

from lumen_ingestion.asset_enrichment import enrich_assets
from lumen_ingestion.describe import DescribeResult

from clue_design.asset_context import (
    AssetAnalysis,
    effective_context,
    fingerprint,
    merge_occurrences,
)


def analysis(title: str = "Product panel", occurrences: list[dict] | None = None) -> dict:
    return AssetAnalysis(
        creative_type="product_screenshot",
        usage_roles=["card_image"],
        classification_reason="A product interface is visible",
        title=title,
        description="A product interface with a navigation sidebar.",
        usage="Use in a feature card where interface details are readable.",
        avoid_when="Avoid as a text background",
        placement="Preserve interface labels",
        tags=["interface"],
        observed={
            "subjects": ["interface"],
            "composition": "sidebar and content",
            "colors": ["white"],
            "readable_text": [],
            "typography": "sans serif",
            "logo_placement": "unknown",
            "negative_space": "little",
            "transparency": "unknown",
        },
        source_interpretations=[
            {
                "occurrence_id": item["occurrence_id"],
                "observed_usage": "supplied placement",
                "logo_relationship": "unknown",
                "relationship_evidence": "",
                "messaging_angle": "",
                "tone": "",
                "cta": "",
                "visual_hierarchy": "",
                "copy_density": "",
                "product_or_use_case_hypothesis": "",
                "audience_hypothesis": "",
                "design_patterns": [],
                "uncertainties": [],
            }
            for item in occurrences or []
        ],
        uncertainties=["Small text is illegible"],
        reuse_boundary="Reference only until rights are confirmed",
    ).model_dump()


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict = {}
        self.lock = threading.Lock()

    def prepare(self, asset_id, inputs, job_id):
        with self.lock:
            old = self.rows.get(asset_id, {})
            inputs = deepcopy(inputs)
            inputs["source_occurrences"] = merge_occurrences(
                old.get("analysis_input", {}).get("source_occurrences", []),
                inputs["source_occurrences"],
            )
            digest = fingerprint(inputs)
            if digest != old.get("input_fingerprint"):
                self.rows[asset_id] = {
                    "status": "queued",
                    "analysis_input": inputs,
                    "input_fingerprint": digest,
                }
            return deepcopy(self.rows[asset_id])

    def begin(self, asset_id, fingerprint, token, job_id):
        with self.lock:
            self.rows[asset_id].update(token=token, status="analyzing")
            return True

    def finish(self, asset_id, token, analysis=None, status="ready", diagnostic=None):
        with self.lock:
            self.rows[asset_id].update(status=status, analysis=analysis, diagnostic=diagnostic)
            return True

    def read(self, asset_id):
        with self.lock:
            return deepcopy(self.rows[asset_id])


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9XcAAAAASUVORK5CYII="
)


def test_137_images_complete_continuously_at_15_with_context_and_partial_persistence():
    scope = ContextVar("test_enrichment_scope", default=None)
    scope.set("job-spend-context")
    store = MemoryStore()
    lock = threading.Lock()
    active = peak = calls = 0
    barrier = threading.Barrier(15)
    observed_progress = []

    class Describer:
        def describe(self, items):
            nonlocal active, peak, calls
            assert len(items) == 1 and scope.get() == "job-spend-context"
            with lock:
                active += 1
                calls += 1
                call = calls
                peak = max(peak, active)
            if call <= 15:
                barrier.wait(timeout=10)
            time.sleep(0.002)
            with lock:
                active -= 1
            data = analysis(occurrences=items[0].source_occurrences)
            return [
                DescribeResult(
                    items[0].asset_id,
                    data["title"],
                    data["description"],
                    data["usage"],
                    data["tags"],
                    data,
                )
            ]

    targets = {f"asset_{i}": {} for i in range(137)}
    result = enrich_assets(
        targets,
        workspace_id="test",
        describer=Describer(),
        store=store,
        resolve_bytes=lambda _: (PNG, "image/png"),
        concurrency=15,
        reporter=lambda *_: observed_progress.append(
            sum(row["status"] == "ready" for row in list(store.rows.values()))
        ),
    )
    assert result["ready"] == calls == 137
    assert result["status"] == "ready" and peak == 15
    assert any(0 < count < 137 for count in observed_progress)
    replay = enrich_assets(
        targets,
        workspace_id="test",
        describer=Describer(),
        store=store,
        resolve_bytes=lambda _: (PNG, "image/png"),
        reporter=lambda *_: None,
    )
    assert replay["cached"] == 137 and calls == 137


def test_failed_preview_keeps_success_and_reports_incomplete():
    class Describer:
        def describe(self, items):
            data = analysis()
            return [
                DescribeResult(
                    items[0].asset_id,
                    data["title"],
                    data["description"],
                    data["usage"],
                    data["tags"],
                    data,
                )
            ]

    store = MemoryStore()
    result = enrich_assets(
        {"good": {}, "bad": {}},
        workspace_id="test",
        store=store,
        describer=Describer(),
        resolve_bytes=lambda aid: ((PNG if aid == "good" else b"bad bytes"), "image/png"),
        reporter=lambda *_: None,
        concurrency=1,
    )
    assert result["ready"] == 1 and result["unsupported"] == 1
    assert result["status"] == "partial"
    assert store.rows["bad"]["diagnostic"]["retryable"]


def test_human_projection_does_not_rewrite_observations_or_provenance():
    generated = analysis()
    result = effective_context(
        {
            "analysis": generated,
            "overrides": {"creative_type": "ad", "usage": "Use as a reference only"},
            "revision": 9,
        }
    )
    assert result["creative_type"] == "ad" and result["classification_origin"] == "human"
    assert result["agent_context"]["guidance"]["usage"] == "Use as a reference only"
    assert result["agent_context"]["observed"] == generated["observed"]
    assert result["source_occurrences"] == []  # An ad classification proves no publication.


# --- Only code calls an asset an ad (spec 2026-10-30 reference ads §5.2) ---------------------

def _typed_row(ai_type: str | None = None, override: str | None = None) -> dict:
    return {
        "asset_id": "a1",
        "analysis": {"creative_type": ai_type} if ai_type else {},
        "overrides": {"creative_type": override} if override else {},
    }


def test_a_harvested_asset_is_an_ad_whatever_the_model_said():
    assert effective_context(_typed_row("photo"), harvested=True)["creative_type"] == "ad"
    assert effective_context(_typed_row(), harvested=True)["creative_type"] == "ad"


def test_a_model_ad_that_was_not_harvested_shows_as_other():
    assert effective_context(_typed_row("ad"))["creative_type"] == "other"


def test_the_persons_type_always_wins():
    assert effective_context(_typed_row("photo", override="ad"))["creative_type"] == "ad"
    context = effective_context(_typed_row("ad", override="photo"), harvested=True)
    assert context["creative_type"] == "photo"
    assert context["classification_origin"] == "human"


def test_other_model_types_are_unchanged():
    assert effective_context(_typed_row("logo"))["creative_type"] == "logo"
    assert effective_context(_typed_row())["creative_type"] == "unknown"


def test_the_model_may_not_answer_ad():
    from clue_design.asset_context import AI_CREATIVE_TYPES

    assert "ad" not in AI_CREATIVE_TYPES and "other" in AI_CREATIVE_TYPES
