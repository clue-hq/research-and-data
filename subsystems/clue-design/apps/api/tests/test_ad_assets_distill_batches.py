"""The ad-style sorting sees every harvested ad and places each one in exactly one group.

Founder ruling 2026-10-19: the sorting used to see only the first 12 ads (Stripe: 12 of 50
grouped; Conduit: 6 of 16), so the turn-time reference picker could only ever attach those.
Now every harvested ad is shown, 12 per vision call; each call's answer must place every ad it
was shown in exactly one group, and is asked once more when it does not; several batches are
combined by one text-only call held to the same rule. No network: the model call is a seam.
"""

from __future__ import annotations

from typing import Any

import pytest

from lumen_ingestion.ad_library import distill
from lumen_ingestion.ad_library.distill import (
    CREATIVES_PER_CALL,
    MAX_STYLE_GROUPS,
    CreativePreview,
    OpenRouterAdDnaDistiller,
    previews_for,
)

PROSE = "A flat green field. The headline is heavy and sits on the left."


def _previews(count: int) -> list[CreativePreview]:
    return [
        CreativePreview(creative_id=f"adcre_{n:02d}", image_b64="aGk=", mime_type="image/png")
        for n in range(count)
    ]


def _image_ids(messages: list[dict]) -> list[str]:
    """The creative ids a vision call was shown, read from its manifest text."""
    text = messages[-1]["content"][0]["text"]
    return [part.split()[0] for part in text.split("creative_id=")[1:]]


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


def _one_look_per_batch(index: int, kind: str, messages: list[dict]) -> dict:
    if kind == "merge":
        text = messages[-1]["content"]
        keys = [line.split("key ")[1].split(":")[0] for line in text.splitlines() if "key " in line]
        return {"prose": PROSE, "style_groups": [{"name": "Green field", "batch_looks": keys}]}
    return {"prose": PROSE, "style_groups": [{"name": f"Look {index}", "creative_ids": _image_ids(messages)}]}


def test_every_harvested_ad_is_shown_twelve_per_call(distiller) -> None:
    calls = _script(distiller, _one_look_per_batch)

    card = distiller.distil(_previews(30))

    batches = [call for call in calls if call["kind"] == "batch"]
    assert [_image_count(call["messages"]) for call in batches] == [CREATIVES_PER_CALL, CREATIVES_PER_CALL, 6]
    assert card is not None
    grouped = [cid for group in card.style_groups for cid in group.creative_ids]
    assert sorted(grouped) == [f"adcre_{n:02d}" for n in range(30)]


def test_several_batches_are_combined_by_one_text_only_call(distiller) -> None:
    calls = _script(distiller, _one_look_per_batch)

    card = distiller.distil(_previews(30))

    merges = [call for call in calls if call["kind"] == "merge"]
    assert len(merges) == 1
    assert isinstance(merges[0]["messages"][-1]["content"], str), "the combining call carries no images"
    assert card is not None and [group.name for group in card.style_groups] == ["Green field"]
    assert card.prose == PROSE


def test_one_batch_needs_no_combining_call(distiller) -> None:
    calls = _script(distiller, _one_look_per_batch)

    card = distiller.distil(_previews(8))

    assert [call["kind"] for call in calls] == ["batch"]
    assert card is not None and len(card.style_groups[0].creative_ids) == 8


def test_a_batch_that_leaves_ads_out_is_asked_once_more_naming_them(distiller) -> None:
    def answer(index: int, kind: str, messages: list[dict]) -> dict:
        ids = _image_ids(messages)
        shown = ids if index else ids[:-2]
        return {"prose": PROSE, "style_groups": [{"name": "Green field", "creative_ids": shown}]}

    calls = _script(distiller, answer)

    card = distiller.distil(_previews(12))

    assert len(calls) == 2
    retry_text = calls[1]["messages"][-1]["content"][0]["text"]
    assert "adcre_10" in retry_text and "adcre_11" in retry_text
    assert card is not None and len(card.style_groups[0].creative_ids) == 12


def test_ads_still_missing_after_the_second_ask_stay_out_and_nothing_fails(distiller) -> None:
    def answer(index: int, kind: str, messages: list[dict]) -> dict:
        ids = _image_ids(messages)
        # Leaves two out, repeats one across groups, and names an id it was never shown.
        return {
            "prose": PROSE,
            "style_groups": [
                {"name": "Green field", "creative_ids": ids[:6] + ["adcre_99"]},
                {"name": "White card", "creative_ids": ids[5:10]},
            ],
        }

    calls = _script(distiller, answer)

    card = distiller.distil(_previews(12))

    assert len(calls) == 2, "asked exactly once more"
    assert card is not None
    grouped = [cid for group in card.style_groups for cid in group.creative_ids]
    assert sorted(grouped) == [f"adcre_{n:02d}" for n in range(10)], "each kept ad appears once"
    assert distiller.last_ungrouped == ("adcre_10", "adcre_11")


def test_the_combining_call_must_place_every_batch_look_exactly_once(distiller) -> None:
    def answer(index: int, kind: str, messages: list[dict]) -> dict:
        if kind == "batch":
            return _one_look_per_batch(index, kind, messages)
        text = messages[-1]["content"]
        keys = [line.split("key ")[1].split(":")[0] for line in text.splitlines() if "key " in line]
        merge_calls = sum(1 for call in calls if call["kind"] == "merge")
        placed = keys if merge_calls == 2 else keys[:-1]
        return {"prose": PROSE, "style_groups": [{"name": "Green field", "batch_looks": placed}]}

    calls = _script(distiller, answer)

    card = distiller.distil(_previews(30))

    merges = [call for call in calls if call["kind"] == "merge"]
    assert len(merges) == 2
    assert "3.1" in merges[1]["messages"][-1]["content"].split("Your previous answer")[1]
    assert card is not None
    assert len(card.style_groups[0].creative_ids) == 30


def test_a_failed_combining_call_falls_back_to_the_batches_own_groups(distiller) -> None:
    def answer(index: int, kind: str, messages: list[dict]) -> Any:
        return None if kind == "merge" else _one_look_per_batch(index, kind, messages)

    _script(distiller, answer)

    card = distiller.distil(_previews(30))

    assert card is not None
    assert [group.name for group in card.style_groups] == ["Look 0", "Look 1", "Look 2"]
    grouped = [cid for group in card.style_groups for cid in group.creative_ids]
    assert sorted(grouped) == [f"adcre_{n:02d}" for n in range(30)]
    assert len(card.style_groups) <= MAX_STYLE_GROUPS


def test_the_sorting_prompt_asks_for_every_ad_in_exactly_one_group() -> None:
    prompt = distill._SYSTEM_PROMPT
    assert "Put every creative_id in exactly one group" in prompt
    assert f"at most {MAX_STYLE_GROUPS} groups" in prompt


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
