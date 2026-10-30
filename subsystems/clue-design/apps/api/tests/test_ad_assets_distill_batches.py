"""The ad-style description sees every harvested ad, 12 per vision call, and is one description.

Founder ruling 2026-10-19: every harvested ad is shown, 12 per vision call; several batches are
combined by one text-only call. Founder ruling 2026-10-30 (reference ads spec §5.3): the card is
a description only — no ad is sorted into a group any more, so no answer is asked to place
anything and nothing is asked twice. No network: the model call is a seam.
"""

from __future__ import annotations

from typing import Any

import pytest

from lumen_ingestion.ad_library import distill
from lumen_ingestion.ad_library.distill import (
    CREATIVES_PER_CALL,
    CreativePreview,
    OpenRouterAdDnaDistiller,
    previews_for,
)

PROSE = "A flat green field. The headline is heavy and sits on the left."
MERGED = "One description of every batch."


def _previews(count: int) -> list[CreativePreview]:
    return [
        CreativePreview(creative_id=f"adcre_{n:02d}", image_b64="aGk=", mime_type="image/png")
        for n in range(count)
    ]


def _image_count(messages: list[dict]) -> int:
    content = messages[-1]["content"]
    return sum(1 for part in content if isinstance(part, dict) and part.get("type") == "image_url")


@pytest.fixture()
def distiller(monkeypatch: pytest.MonkeyPatch) -> OpenRouterAdDnaDistiller:
    monkeypatch.setattr(distill.settings, "lumen_brand_ad_assets", True, raising=False)
    monkeypatch.setattr(distill.settings, "openrouter_api_key", "a-key", raising=False)
    engine = OpenRouterAdDnaDistiller()
    assert engine.active
    return engine


def _script(engine: OpenRouterAdDnaDistiller, answer) -> list[dict[str, Any]]:
    """Replace the model call with `answer(call_index, kind, messages)`; record every call."""
    calls: list[dict[str, Any]] = []

    def fake_call(*, messages, schema_name, schema, label):
        del schema, label
        kind = "merge" if schema_name == "ad_dna_merge" else "batch"
        calls.append({"kind": kind, "messages": messages})
        return answer(len(calls) - 1, kind, messages)

    engine._call = fake_call  # type: ignore[method-assign]
    return calls


def _describe(index: int, kind: str, messages: list[dict]) -> dict:
    return {"prose": MERGED if kind == "merge" else f"{PROSE} (batch {index})"}


def test_every_harvested_ad_is_shown_twelve_per_call(distiller) -> None:
    calls = _script(distiller, _describe)

    card = distiller.distil(_previews(30))

    batches = [call for call in calls if call["kind"] == "batch"]
    assert [_image_count(call["messages"]) for call in batches] == [CREATIVES_PER_CALL, CREATIVES_PER_CALL, 6]
    assert card is not None


def test_several_batches_are_combined_into_one_description(distiller) -> None:
    calls = _script(distiller, _describe)

    card = distiller.distil(_previews(30))

    merges = [call for call in calls if call["kind"] == "merge"]
    assert len(merges) == 1
    assert isinstance(merges[0]["messages"][-1]["content"], str), "the combining call carries no images"
    assert "(batch 2)" in merges[0]["messages"][-1]["content"]
    assert card is not None and card.prose == MERGED
    assert card.to_json()["style_groups"] == []


def test_one_batch_needs_no_combining_call(distiller) -> None:
    calls = _script(distiller, _describe)

    card = distiller.distil(_previews(8))

    assert [call["kind"] for call in calls] == ["batch"]
    assert card is not None and card.prose == f"{PROSE} (batch 0)"


def test_each_batch_is_asked_once(distiller) -> None:
    calls = _script(distiller, _describe)

    distiller.distil(_previews(12))

    assert len(calls) == 1


def test_a_failed_combining_call_falls_back_to_the_first_batchs_description(distiller) -> None:
    def answer(index: int, kind: str, messages: list[dict]) -> Any:
        return None if kind == "merge" else _describe(index, kind, messages)

    _script(distiller, answer)

    card = distiller.distil(_previews(30))

    assert card is not None and card.prose == f"{PROSE} (batch 0)"


def test_no_prompt_or_schema_asks_for_groups() -> None:
    removed = (
        "Then group the creatives",
        "exactly one group",
        "Then combine the batch looks",
        "its own named looks",
    )
    for prompt in (distill._SYSTEM_PROMPT, distill._MERGE_PROMPT):
        assert not any(sentence in prompt for sentence in removed)
    batch_text = distill._batch_messages(_previews(1), None)[1]["content"][0]["text"]
    assert "then group them" not in batch_text
    assert set(distill._CARD_SCHEMA["properties"]) == {"prose"}
    assert set(distill._MERGE_SCHEMA["properties"]) == {"prose"}


def test_a_payload_carrying_groups_still_stores_none() -> None:
    card = distill.bounded_card(
        {"prose": "x", "style_groups": [{"name": "A", "creative_ids": ["c1"]}]}
    )
    assert card is not None and card.to_json()["style_groups"] == []


def test_previews_are_built_for_every_harvested_ad() -> None:
    class _Ad:
        headline_title = "Headline"
        image_alt_text = None

    class _Creative:
        def __init__(self, n: int) -> None:
            self.creative_id = f"adcre_{n:02d}"
            self.image_bytes = b"bytes"
            self.ad = _Ad()

    previews = previews_for([_Creative(n) for n in range(50)], downscale=lambda data: "aGk=")

    assert len(previews) == 50
